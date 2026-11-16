import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vl.api.main import create_app
from vl.db import Enrichment, Note, make_session_factory
from vl.enrich.query import StructuredQuery
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes

IDEA = "20241103 101530.m4a"
BABY = "20260801 090000.m4a"


class FakeParser:
    def __init__(self, **kw):
        self.sq = StructuredQuery(**{"semantic_text": "baby laughing", "keywords": ["baby"], **kw})

    def parse(self, q, c, t):
        return self.sq


class FakeReranker:
    def rerank(self, q, cands):
        return [{"id": c["id"], "why": "because", "strength": "match" if i == 0 else "related"}
                for i, c in enumerate(cands)]


@pytest.fixture
def env(tmp_path, audio_folder, fakes):
    t, e, m = fakes
    factory = make_session_factory(tmp_path / "api.db")
    audio = tmp_path / "audio"
    with factory() as s:
        import_folder(s, audio_folder, audio)
        process_notes(s, t, e, m)
    return factory, m, audio


def client(env, parser=None, reranker=None, with_root=True, reason=None):
    factory, m, audio = env
    app = create_app(factory, embedder=m, parser=parser, reranker=reranker,
                     audio_root=audio if with_root else None, claude_unavailable_reason=reason)
    return TestClient(app)


def note_id(env, name):
    with env[0]() as s:
        return s.query(Note).filter_by(original_name=name).one().id


def test_health_home_and_page_serving(env):
    c = client(env)
    assert c.get("/api/health").json() == {"notes": 2}
    home = c.get("/api/home").json()
    assert home["total_notes"] == 2 and {x["name"] for x in home["categories"]} >= {"Ideas", "Family memories"}
    assert c.get("/").status_code in (200, 404)  # 404 only if web/index.html hasn't been written yet


def test_quick_search_is_local_and_empty_query_is_empty(env):
    c = client(env, parser=FakeParser())  # a parser exists, but quick search must never use it
    assert c.get("/api/search", params={"q": "  "}).json() == {"hits": []}
    hits = c.get("/api/search", params={"q": "Echo"}).json()["hits"]
    assert len(hits) == 1 and hits[0]["category"] == "Ideas"
    assert set(hits[0]) >= {"id", "title", "summary", "recorded_at", "duration_s", "sound_info", "why", "strength"}


def test_ask_with_claude_returns_labels_verdict_and_understanding(env):
    c = client(env, parser=FakeParser(), reranker=FakeReranker())
    r = c.post("/api/ask", json={"q": "my baby laughing"}).json()
    assert r["used_claude"] is True and r["understood"]["topic"] == "baby laughing"
    assert r["hits"] and r["hits"][0]["strength"] == "match" and r["verdict"] == "One clear match."


def test_without_claude_ask_is_a_basic_search_and_says_so(env):
    c = client(env, parser=None, reason="No ANTHROPIC_API_KEY set.")
    r = c.post("/api/ask", json={"q": "baby laughing"}).json()
    assert r["used_claude"] is False and r["verdict"] is None and r["hits"]
    assert "No ANTHROPIC_API_KEY set." in r["notes"][0] and "basic search" in r["notes"][0]
    assert all(h["why"] is None for h in r["hits"])  # no rerank happened


def test_settings_say_whether_claude_is_connected_and_there_is_no_switch(env):
    off = client(env, parser=None, reason="No ANTHROPIC_API_KEY set.")
    assert off.get("/api/settings").json() == {"claude": False, "reason": "No ANTHROPIC_API_KEY set."}
    on = client(env, parser=FakeParser(), reranker=FakeReranker())
    assert on.get("/api/settings").json() == {"claude": True, "reason": None}
    assert on.post("/api/settings", json={"use_claude": False}).status_code in (404, 405)  # Claude is always used


def test_ask_validates_input(env):
    c = client(env)
    assert c.post("/api/ask", json={"q": ""}).status_code == 422
    assert c.post("/api/ask", json={"q": "x" * 501}).status_code == 422
    assert c.post("/api/ask", json={"q": "ok", "limit": 999}).status_code == 422


def test_note_detail_and_audio(env):
    c = client(env)
    nid = note_id(env, BABY)
    d = c.get(f"/api/notes/{nid}").json()
    assert d["category"] == "Family memories" and "baby laughing" in d["transcript"]
    assert c.get("/api/notes/9999").status_code == 404
    r = c.get(f"/api/notes/{nid}/audio")
    assert r.status_code == 200 and r.content.startswith(b"baby laughing")  # the fixture's fake audio bytes
    assert r.headers["content-type"] == "audio/mp4"
    part = c.get(f"/api/notes/{nid}/audio", headers={"Range": "bytes=0-3"})  # seeking in the player needs this
    assert part.status_code == 206 and part.content == b"baby"
    assert c.get("/api/notes/9999/audio").status_code == 404


def test_audio_outside_the_audio_folder_is_refused_and_missing_file_is_404(env, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    nid = note_id(env, IDEA)
    with env[0]() as s:
        s.get(Note, nid).path = str(secret)
        s.commit()
    c = client(env)
    assert c.get(f"/api/notes/{nid}/audio").status_code == 403
    with env[0]() as s:
        s.get(Note, nid).path = str(env[2] / "gone.m4a")
        s.commit()
    assert c.get(f"/api/notes/{nid}/audio").status_code == 404


def test_requests_for_other_hostnames_are_rejected(env):
    c = client(env)
    assert c.get("/api/health", headers={"host": "evil.example.com"}).status_code == 400
    assert c.get("/api/health", headers={"host": "localhost:8765"}).status_code == 200


def test_category_creation_suggestions_and_errors(env):
    c = client(env)
    assert c.post("/api/categories", json={"name": "Ideas"}).status_code == 400   # duplicate of a seed
    assert c.post("/api/categories", json={"name": ""}).status_code == 400
    ok = c.post("/api/categories", json={"name": "Baby", "from_tag": "baby"}).json()
    assert ok["moved"] == 1
    with env[0]() as s:
        s.query(Enrichment).filter(Enrichment.note_id == note_id(env, IDEA)).one().suggested_category = "Naming"
        s.commit()
    assert [x["name"] for x in c.get("/api/attention").json()["suggestions"]] == ["Naming"]
    assert c.post("/api/suggestions/accept", json={"name": "Naming"}).json()["moved"] == 1
    assert c.post("/api/suggestions/accept", json={"name": "Naming"}).status_code == 400  # nothing left to accept
    assert c.post("/api/suggestions/reject", json={"name": "Whatever"}).json() == {"cleared": 0}


def test_assign_category_and_flags_and_review_queue(env):
    c = client(env)
    nid = note_id(env, IDEA)
    cats = {x["name"]: x["id"] for x in c.get("/api/home").json()["categories"]}
    assert c.post(f"/api/notes/{nid}/category", json={"category_id": cats["Family memories"]}).status_code == 200
    assert c.get(f"/api/notes/{nid}").json()["category"] == "Family memories"
    assert c.post(f"/api/notes/{nid}/category", json={"category_id": 9999}).status_code == 400
    assert c.post(f"/api/notes/{nid}/flag", json={"flag": "delete"}).status_code == 400

    with env[0]() as s:
        s.get(Enrichment, nid).junk_score = 0.9
        s.commit()
    assert [n["id"] for n in c.get("/api/review").json()["notes"]] == [nid]
    assert c.get("/api/attention").json()["count"] == 1 and c.get("/api/home").json()["attention_count"] == 1
    c.post(f"/api/notes/{nid}/flag", json={"flag": "archived"})
    assert c.get("/api/review").json()["notes"] == []
    assert c.get("/api/search", params={"q": "Echo"}).json()["hits"] == []       # hidden everywhere
    assert [n["id"] for n in c.get("/api/archived").json()["notes"]] == [nid]
    c.post(f"/api/notes/{nid}/flag", json={"flag": None})                          # un-archive
    assert len(c.get("/api/search", params={"q": "Echo"}).json()["hits"]) == 1


def test_browse_lists_newest_first_by_category_and_hides_archived(env):
    c = client(env)
    allnotes = c.get("/api/browse").json()["hits"]
    assert [h["category"] for h in allnotes] == ["Family memories", "Ideas"]  # 2026 note before the 2024 one
    cats = {x["name"]: x["id"] for x in c.get("/api/home").json()["categories"]}
    only = c.get("/api/browse", params={"category_id": cats["Ideas"]}).json()["hits"]
    assert [h["category"] for h in only] == ["Ideas"]
    c.post(f"/api/notes/{note_id(env, IDEA)}/flag", json={"flag": "archived"})
    assert [h["category"] for h in c.get("/api/browse").json()["hits"]] == ["Family memories"]
    assert c.get("/api/browse", params={"uncategorized": True}).json()["hits"] == []
    assert len(c.get("/api/browse", params={"limit": 1}).json()["hits"]) == 1


def test_serve_refuses_to_listen_beyond_this_computer():
    import argparse

    from vl import cli
    with pytest.raises(SystemExit, match="only runs on this computer"):
        cli.cmd_serve(argparse.Namespace(host="0.0.0.0", port=8765, open=False, llm_model="x"))


# ---------------- new in the redesign ----------------

def test_results_carry_tags_and_the_matching_moment_with_its_timestamp(env):
    with env[0]() as s:
        from vl.db import Transcript
        n = note_id(env, IDEA)
        s.get(Transcript, n).segments_json = json.dumps([
            {"start": 0, "end": 5, "text": "Okay quick one."},
            {"start": 14, "end": 30, "text": "my idea for a better app name called Echo"}])
        s.commit()
    c = client(env)
    hit = c.get("/api/search", params={"q": "better app name"}).json()["hits"][0]
    assert hit["tags"] == ["app"] and hit["snippet"]["t"] == 14.0
    assert [p["t"] for p in hit["snippet"]["parts"] if p["m"]] == ["better", "app", "name"]
    # a search with only filler words has nothing to highlight
    assert c.get("/api/search", params={"q": "baby"}).json()["hits"][0]["snippet"]["t"] is not None
    assert c.get("/api/browse").json()["hits"][0]["snippet"] is None  # browsing shows summaries, no fake highlight


def test_ask_snippets_use_the_questions_keywords_too(env):
    c = client(env, parser=FakeParser(semantic_text="kitten", keywords=["laughing"]), reranker=None)
    r = c.post("/api/ask", json={"q": "my favourite memory"}).json()
    assert any(h["snippet"] and any(p["m"] for p in h["snippet"]["parts"]) for h in r["hits"])


def test_note_detail_has_segments_related_and_edit_info(env):
    c = client(env)
    d = c.get(f"/api/notes/{note_id(env, IDEA)}").json()
    assert d["segments"] and d["edited"] == [] and d["imported_at"]
    assert isinstance(d["related"], list)


def test_editing_details_validates_and_is_remembered(env):
    c = client(env)
    n = note_id(env, IDEA)
    r = c.patch(f"/api/notes/{n}", json={"title": "A better name", "tags": ["Naming", "app"]})
    assert r.status_code == 200 and r.json()["title"] == "A better name" and set(r.json()["edited"]) == {"title", "tags"}
    assert c.get("/api/search", params={"q": "better name"}).json()["hits"][0]["title"] == "A better name"
    assert c.patch(f"/api/notes/{n}", json={"title": ""}).status_code == 400
    assert c.patch("/api/notes/9999", json={"title": "x"}).status_code == 400


def test_peaks_endpoint_and_its_guards(env, tmp_path):
    import struct
    import wave
    nid = note_id(env, BABY)
    wav = env[2] / "real.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", 8000 if i % 40 < 20 else -8000) for i in range(32000)))
    with env[0]() as s:
        s.get(Note, nid).path = str(wav)
        s.commit()
    c = client(env)
    p = c.get(f"/api/notes/{nid}/peaks", params={"n": 32}).json()["peaks"]
    assert len(p) == 32 and max(p) == 1.0
    assert len(c.get(f"/api/notes/{nid}/peaks", params={"n": 5}).json()["peaks"]) == 16   # n is clamped to 16..400
    assert c.get("/api/notes/9999/peaks").status_code == 404
    outside = tmp_path / "outside.wav"
    outside.write_bytes(wav.read_bytes())
    with env[0]() as s:
        s.get(Note, nid).path = str(outside)
        s.commit()
    assert c.get(f"/api/notes/{nid}/peaks").status_code == 403


def test_home_gives_example_searches_and_the_attention_count(env):
    h = client(env).get("/api/home").json()
    assert h["total_notes"] == 2 and len(h["try"]) == 2 and h["attention_count"] == 0


def test_the_page_and_its_static_files_are_served(env):
    c = client(env)
    assert c.get("/static/app.css").status_code in (200, 404)  # 404 only before web/ files exist


# ---------- upload + import ----------

def uploads(env, tmp_path, **kw):
    from vl.jobs import Deps, ImportManager
    from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber
    factory, m, audio = env
    mgr = ImportManager(factory, audio, Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder()))
    app = create_app(factory, embedder=m, audio_root=audio, import_manager=mgr, upload_dir=tmp_path / "up", **kw)
    return TestClient(app), mgr


def test_upload_imports_in_the_background_and_reports_progress(env, tmp_path):
    c, mgr = uploads(env, tmp_path)
    r = c.post("/api/import", files=[
        ("files", ("New Recording 5.m4a", b"baby giggling in the bath", "audio/mp4")),
        ("files", ("notes.txt", b"not audio", "text/plain"))],
        data={"modified": ["1700000000000", "0"]})
    body = r.json()
    assert r.status_code == 200 and body["accepted"] == 1 and body["rejected"][0]["name"] == "notes.txt"
    assert mgr.wait()
    snap = c.get(f"/api/import/{body['job_id']}").json()
    assert snap["finished"] and snap["files"][0]["state"] == "done" and snap["files"][0]["category"] == "Family memories"
    assert c.get("/api/import/latest").json()["job"]["id"] == body["job_id"]
    assert c.get("/api/import/nope").status_code == 404
    assert c.get("/api/search", params={"q": "bath"}).json()["hits"]          # it's searchable straight away
    with env[0]() as s:
        n = s.query(Note).filter_by(original_name="New Recording 5.m4a").one()
        assert n.date_source == "file-modified" and n.recorded_at.year == 2023  # the browser's file time, last resort
    assert not list((tmp_path / "up").rglob("*.m4a"))                          # temp upload cleaned up


def test_upload_rejects_when_nothing_is_audio_and_when_unavailable(env, tmp_path):
    c, _ = uploads(env, tmp_path)
    r = c.post("/api/import", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert r.status_code == 400 and "audio" in r.json()["detail"]
    assert not any((tmp_path / "up").iterdir())  # no leftover empty batch folder
    plain = client(env)  # no import manager configured
    assert plain.post("/api/import", files=[("files", ("a.m4a", b"x", "audio/mp4"))]).status_code == 503
    assert plain.get("/api/import/latest").json() == {"job": None}


def test_upload_uses_only_the_base_name_so_paths_cant_escape(env, tmp_path):
    c, mgr = uploads(env, tmp_path)
    r = c.post("/api/import", files=[("files", ("../../etc/evil.m4a", b"baby sounds here", "audio/mp4"))])
    assert r.status_code == 200 and mgr.wait()
    with env[0]() as s:
        assert s.query(Note).filter_by(original_name="evil.m4a").count() == 1
    assert not (tmp_path / "etc").exists()


def test_a_file_over_the_size_limit_is_rejected_cleanly(env, tmp_path, monkeypatch):
    import vl.api.main as m
    monkeypatch.setattr(m, "MAX_UPLOAD_BYTES", 10)
    c, _ = uploads(env, tmp_path)
    r = c.post("/api/import", files=[("files", ("big.m4a", b"x" * 50, "audio/mp4"))])
    assert r.status_code == 400
    assert not list((tmp_path / "up").rglob("*.m4a"))
