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


def test_ask_with_claude_off_runs_locally_and_says_so(env):
    c = client(env, parser=FakeParser(), reranker=FakeReranker())
    assert c.post("/api/settings", json={"use_claude": False}).json()["use_claude"] is False
    r = c.post("/api/ask", json={"q": "baby laughing"}).json()
    assert r["used_claude"] is False and r["verdict"] is None
    assert r["notes"][0].startswith("Claude is off") and r["hits"]
    assert all(h["why"] is None for h in r["hits"])  # no rerank happened


def test_claude_cannot_be_enabled_when_not_configured(env):
    c = client(env, parser=None, reason="No ANTHROPIC_API_KEY set.")
    s = c.get("/api/settings").json()
    assert s == {"use_claude": False, "claude_available": False, "reason": "No ANTHROPIC_API_KEY set."}
    r = c.post("/api/settings", json={"use_claude": True})
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert c.post("/api/ask", json={"q": "baby"}).json()["used_claude"] is False  # still works, locally


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
    assert [x["name"] for x in c.get("/api/home").json()["suggestions"]] == ["Naming"]
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
    assert c.get("/api/home").json()["review_count"] == 1
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
