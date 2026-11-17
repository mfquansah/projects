import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vl.api.main import create_app
from vl.batch import build_report, pick_new, remaining_audio_seconds
from vl.db import Note, make_session_factory
from vl.enrich.llm import ClaudeEnricher
from vl.jobs import Deps, ImportManager
from vl.usage import UsageMeter, record_message
from vl.voicememos import newest_first

from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


# ---------- usage meter ----------

def test_meter_counts_calls_and_tokens_and_tolerates_missing_usage():
    m = UsageMeter()
    record_message(m, SimpleNamespace(usage=SimpleNamespace(input_tokens=120, output_tokens=30)))
    record_message(m, SimpleNamespace())                                   # a reply with no usage info still counts as a call
    record_message(m, SimpleNamespace(usage=SimpleNamespace(input_tokens=None, output_tokens=5)))
    record_message(None, SimpleNamespace())                                # no meter: nothing happens
    assert m.snapshot() == {"calls": 3, "input_tokens": 120, "output_tokens": 35}


def test_meter_is_thread_safe():
    m = UsageMeter()
    ts = [threading.Thread(target=lambda: [m.add(1, 2) for _ in range(500)]) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert m.snapshot() == {"calls": 4000, "input_tokens": 4000, "output_tokens": 8000}


class _Msg:
    def __init__(self, text, usage=True):
        self.content = [SimpleNamespace(type="text", text=text)]
        self.stop_reason = "end_turn"
        if usage:
            self.usage = SimpleNamespace(input_tokens=200, output_tokens=40)


class _Client:
    def __init__(self, replies):
        self.messages, self.replies = self, list(replies)

    def create(self, **kw):
        return self.replies.pop(0)


GOOD = '{"title":"T","summary":"S","category":"Ideas","tags":["a"],"junk_score":0.1}'


def test_enricher_reports_usage_including_the_retry():
    m = UsageMeter()
    e = ClaudeEnricher(client=_Client([_Msg("no json here"), _Msg(GOOD)]), meter=m)
    e.enrich("hello there", ["Ideas", "Other"], None)
    assert m.snapshot() == {"calls": 2, "input_tokens": 400, "output_tokens": 80}   # the retry costs a second call


# ---------- report arithmetic ----------

def f(name, state="done", seconds=0.0, audio_s=None, tin=0, tout=0, calls=1, error=""):
    return {"name": name, "state": state, "seconds": seconds, "audio_s": audio_s, "tokens_in": tin, "tokens_out": tout,
            "calls": calls, "error": error}


def test_report_numbers_are_computed_from_processed_notes_only():
    files = [f("a", seconds=60, audio_s=120, tin=1000, tout=100), f("b", seconds=120, audio_s=240, tin=2000, tout=200),
             f("c", state="error", seconds=5, error="cannot decode"), f("d", state="duplicate")]
    r = build_report(files, remaining_files=10, remaining_audio_s=3600)          # 60 min of audio left
    assert r["processed"] == 2 and r["duplicates"] == 1 and r["failed"] == [{"name": "c", "error": "cannot decode"}]
    assert r["seconds"] == {"total": 180, "mean": 90, "median": 90, "max": 120}
    assert r["audio_minutes"] == pytest.approx(6.0)
    assert r["seconds_per_audio_minute"] == pytest.approx(30.0)                  # 180 s of work for 6 min of audio
    assert r["tokens"] == {"input": 3000, "output": 300, "calls": 2}
    assert r["cost_usd"] is None                                                  # no prices given: tokens only, no invented dollars
    rem = r["remaining"]
    assert rem["files"] == 10 and rem["basis"] == "audio length" and rem["audio_minutes"] == pytest.approx(60)
    assert rem["est_seconds"] == pytest.approx(1800)                              # 30 s per audio minute x 60 min
    assert rem["est_tokens"] == {"input": 30000, "output": 3000}                  # tokens scale with audio: 10x the 6 min batch
    assert [s["name"] for s in r["slowest"]] == ["b", "a"]


def test_report_cost_uses_prices_when_given():
    files = [f("a", seconds=10, audio_s=60, tin=1_000_000, tout=200_000)]
    r = build_report(files, 0, 0.0, price_in=1.0, price_out=5.0)                  # $ per million tokens
    assert r["cost_usd"] == pytest.approx(1.0 + 1.0)
    assert r["remaining"] is None


def test_report_falls_back_to_per_recording_when_lengths_are_unknown():
    files = [f("a", seconds=40, audio_s=None, tin=500, tout=50), f("b", seconds=60, audio_s=None, tin=500, tout=50)]
    r = build_report(files, remaining_files=8, remaining_audio_s=None)
    assert r["seconds_per_audio_minute"] is None
    assert r["remaining"]["basis"] == "per recording" and r["remaining"]["est_seconds"] == pytest.approx(400)
    assert r["remaining"]["est_tokens"] == {"input": 4000, "output": 400}


def test_report_with_nothing_processed_has_no_estimate_and_does_not_divide_by_zero():
    r = build_report([f("x", state="error", error="boom")], 50, 1000.0)
    assert r["processed"] == 0 and r["seconds"]["mean"] is None and r["seconds_per_audio_minute"] is None and r["remaining"] is None
    assert build_report([], 0, None)["processed"] == 0


# ---------- ordering and picking ----------

def test_newest_first_uses_the_name_date_then_modified_time(tmp_path):
    a = tmp_path / "20240101 090000-AAA.m4a"
    b = tmp_path / "20260301 090000-BBB.m4a"
    c = tmp_path / "20250101 090000-CCC.m4a"
    d = tmp_path / "New Recording 7.m4a"          # no date in the name: modified time (now) is newest
    for p in (a, b, c, d):
        p.write_bytes(b"x")
    assert newest_first([a, b, c, d]) == [d, b, c, a]


def test_pick_new_skips_what_is_already_imported(tmp_path):
    factory = make_session_factory(tmp_path / "x.db")
    files = []
    for i in range(5):
        p = tmp_path / f"{i}.m4a"
        p.write_bytes(f"recording {i}".encode())
        files.append(p)
    with factory() as s:
        from vl.db import Enrichment
        from vl.ingest.importer import import_one
        for i in (0, 1):                           # the two newest are already in the library, fully processed
            note, _ = import_one(s, files[i], tmp_path / "store")
            s.add(Enrichment(note_id=note.id, title="t", summary="s", tags_json="[]", model_version="x"))
        s.commit()
        got = pick_new(files, 2, s)
    assert got == [files[2], files[3]]


def test_remaining_audio_uses_known_lengths_and_estimates_the_unreadable(tmp_path, monkeypatch):
    import vl.batch as b
    lens = {"a.m4a": 60.0, "b.m4a": None, "c.m4a": 120.0}
    monkeypatch.setattr(b, "probe_duration", lambda p: lens[p.name])
    rest = [Path("a.m4a"), Path("b.m4a"), Path("c.m4a")]
    assert remaining_audio_seconds(rest, fallback_mean_s=30.0) == pytest.approx(60 + 120 + 30)
    assert remaining_audio_seconds([], 30.0) == 0.0
    monkeypatch.setattr(b, "probe_duration", lambda p: None)
    assert remaining_audio_seconds(rest, 30.0) == 90.0 and remaining_audio_seconds(rest, None) is None


# ---------- per-file timing and usage in the importer ----------

class MeteredEnricher(FakeEnricher):
    def __init__(self, meter):
        self.meter = meter

    def enrich(self, transcript, categories, recorded_at):
        self.meter.add(300, 60)
        return super().enrich(transcript, categories, recorded_at)


class SlowTranscriber(FakeTranscriber):
    def __init__(self, gate=None):
        self.gate = gate

    def transcribe(self, path, progress=None):
        if self.gate:
            self.gate.wait(10)
        time.sleep(0.05)
        return super().transcribe(path, progress)


def test_each_file_records_seconds_stages_and_its_own_claude_usage(tmp_path):
    factory = make_session_factory(tmp_path / "j.db")
    meter = UsageMeter()
    mgr = ImportManager(factory, tmp_path / "store", Deps(SlowTranscriber(), MeteredEnricher(meter), FakeEmbedder(), None, meter))
    p1, p2 = tmp_path / "a.m4a", tmp_path / "b.m4a"
    p1.write_bytes(b"baby giggling"); p2.write_bytes(b"my idea for an app")
    jid = mgr.submit([("a.m4a", p1, None, False), ("b.m4a", p2, None, False)])
    assert mgr.wait()
    files = mgr.snapshot(jid)["files"]
    for x in files:
        assert x["state"] == "done" and x["seconds"] >= 0.05
        assert x["calls"] == 1 and x["tokens_in"] == 300 and x["tokens_out"] == 60      # per file, not cumulative
        assert {"import", "transcribe", "enrich", "index"} <= set(x["stages"])
        assert x["stages"]["transcribe"] >= 0.05
    assert meter.snapshot()["calls"] == 2


def test_duplicates_are_not_timed_and_failures_still_are(tmp_path):
    factory = make_session_factory(tmp_path / "j.db")
    meter = UsageMeter()

    class Boom(FakeTranscriber):
        def transcribe(self, path, progress=None):
            if b"corrupt" in path.read_bytes():
                raise RuntimeError("cannot decode")
            return super().transcribe(path, progress)

    mgr = ImportManager(factory, tmp_path / "store", Deps(Boom(), MeteredEnricher(meter), FakeEmbedder(), None, meter))
    a, bad = tmp_path / "a.m4a", tmp_path / "bad.m4a"
    a.write_bytes(b"baby"); bad.write_bytes(b"corrupt")
    mgr.submit([("a.m4a", a, None, False), ("bad.m4a", bad, None, False)]); assert mgr.wait()
    jid = mgr.submit([("again.m4a", a, None, False), ("bad.m4a", bad, None, False)]); assert mgr.wait()
    again, badagain = mgr.snapshot(jid)["files"]
    assert again["state"] == "duplicate" and again["seconds"] == 0 and again["calls"] == 0
    assert badagain["state"] == "error" and {"import", "transcribe"} <= set(badagain["stages"])   # a failure is still timed


# ---------- API ----------

@pytest.fixture
def api(tmp_path):
    factory = make_session_factory(tmp_path / "api.db")
    meter = UsageMeter()
    gate = threading.Event()
    gate.set()
    mgr = ImportManager(factory, tmp_path / "audio", Deps(SlowTranscriber(gate), MeteredEnricher(meter), FakeEmbedder(), None, meter))
    app = create_app(factory, embedder=FakeEmbedder(), audio_root=tmp_path / "audio", import_manager=mgr, upload_dir=tmp_path / "up")
    folder = tmp_path / "vm"
    folder.mkdir()
    for i, day in enumerate(["20260101", "20260105", "20260110", "20260115", "20260120"]):
        (folder / f"{day} 090000-{i}.m4a").write_bytes(f"recording number {i} about baby sounds".encode())
    return TestClient(app), mgr, folder, gate, factory


def test_a_test_batch_takes_the_newest_unimported_and_reports(api):
    c, mgr, folder, gate, factory = api
    r = c.post("/api/import/folder", json={"path": str(folder), "newest": 2}).json()
    assert r["accepted"] == 2 and r["batch"] is True
    assert mgr.wait()
    snap = c.get(f"/api/import/{r['job_id']}").json()
    assert [x["name"] for x in snap["files"]] == ["20260120 090000-4.m4a", "20260115 090000-3.m4a"]    # newest first
    assert snap["meta"]["batch"] is True and snap["meta"]["total_files"] == 5
    rep = c.get(f"/api/import/{r['job_id']}/report").json()
    assert rep["batch"] is True and rep["processed"] == 2 and rep["tokens"] == {"input": 600, "output": 120, "calls": 2}
    assert rep["remaining"]["files"] == 3 and rep["remaining"]["est_seconds"] > 0
    assert rep["cost_usd"] is None and rep["prices_set"] is False
    # the next batch skips what's already in, taking the next-newest
    r2 = c.post("/api/import/folder", json={"path": str(folder), "newest": 2}).json()
    assert mgr.wait()
    assert [x["name"] for x in c.get(f"/api/import/{r2['job_id']}").json()["files"]] == ["20260110 090000-2.m4a", "20260105 090000-1.m4a"]


def test_report_shows_dollars_only_when_prices_are_set(api, monkeypatch):
    c, mgr, folder, gate, factory = api
    jid = c.post("/api/import/folder", json={"path": str(folder), "newest": 1}).json()["job_id"]
    assert mgr.wait()
    monkeypatch.setenv("VL_PRICE_IN_PER_MTOK", "1.0")
    monkeypatch.setenv("VL_PRICE_OUT_PER_MTOK", "5.0")
    rep = c.get(f"/api/import/{jid}/report").json()
    assert rep["prices_set"] is True and rep["cost_usd"] == pytest.approx((300 * 1.0 + 60 * 5.0) / 1e6)
    monkeypatch.setenv("VL_PRICE_IN_PER_MTOK", "not a number")
    assert c.get(f"/api/import/{jid}/report").json()["prices_set"] is False


def test_report_refuses_while_running_and_for_unknown_jobs(api):
    c, mgr, folder, gate, factory = api
    gate.clear()                                                   # the transcriber now blocks
    jid = c.post("/api/import/folder", json={"path": str(folder), "newest": 1}).json()["job_id"]
    assert c.get(f"/api/import/{jid}/report").status_code == 409
    gate.set()
    assert mgr.wait()
    assert c.get(f"/api/import/{jid}/report").status_code == 200
    assert c.get("/api/import/nope/report").status_code == 404


def test_batch_with_everything_already_imported_says_so(api):
    c, mgr, folder, gate, factory = api
    c.post("/api/import/folder", json={"path": str(folder)}); assert mgr.wait()
    r = c.post("/api/import/folder", json={"path": str(folder), "newest": 3})
    assert r.status_code == 400 and "already in your library" in r.json()["detail"]
    assert c.post("/api/import/folder", json={"path": str(folder), "newest": 0}).status_code == 422
    assert c.post("/api/import/folder", json={"path": str(folder), "newest": 501}).status_code == 422


def test_a_full_folder_import_is_also_newest_first(api):
    c, mgr, folder, gate, factory = api
    jid = c.post("/api/import/folder", json={"path": str(folder)}).json()["job_id"]
    assert mgr.wait()
    names = [x["name"] for x in c.get(f"/api/import/{jid}").json()["files"]]
    assert names == sorted(names, reverse=True) and c.get(f"/api/import/{jid}").json()["meta"]["batch"] is False
    with factory() as s:
        assert s.query(Note).count() == 5


def test_pick_new_includes_recordings_that_were_imported_but_never_finished(tmp_path):
    from vl.db import Enrichment
    from vl.ingest.importer import import_one
    factory = make_session_factory(tmp_path / "x.db")
    files = []
    for i in range(3):
        p = tmp_path / f"{i}.m4a"
        p.write_bytes(f"recording {i}".encode())
        files.append(p)
    with factory() as s:
        done, half, _ = [import_one(s, p, tmp_path / "store")[0] for p in files[:2]] + [None]
        s.add(Enrichment(note_id=done.id, title="t", summary="s", tags_json="[]", model_version="x"))   # file 0 finished
        s.commit()                                                                                         # file 1 was stopped part-way
        assert pick_new(files, 3, s) == [files[1], files[2]]
