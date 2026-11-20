import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import vl.sync as sync_mod
from vl.api.main import create_app
from vl.db import Note, make_session_factory
from vl.jobs import Deps, ImportManager
from vl.sync import MAX_FAILURES, SyncManager
from vl.voicememos import PERMISSION_HELP, icloud_placeholders

from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


class Flaky(FakeTranscriber):
    def transcribe(self, path, progress=None):
        if b"corrupt" in path.read_bytes():
            raise RuntimeError("cannot decode")
        return super().transcribe(path, progress)


@pytest.fixture
def env(tmp_path):
    folder = tmp_path / "vm"
    folder.mkdir()
    (folder / "20260101 090000-AAA.m4a").write_bytes(b"baby giggling in the bath")
    (folder / "20260102 090000-BBB.m4a").write_bytes(b"my idea for an app")
    factory = make_session_factory(tmp_path / "lib.db")
    holder = {}
    mgr = ImportManager(factory, tmp_path / "audio", Deps(Flaky(), FakeEnricher(), FakeEmbedder()),
                        on_file_done=lambda f: holder["sync"].on_file_done(f))
    sync = holder["sync"] = SyncManager(mgr, tmp_path / "state", source_resolver=lambda s: (folder, None))
    return sync, mgr, folder, factory


def settle(mgr):
    assert mgr.wait()
    time.sleep(0.05)  # the done-hook runs just after the file's state flips


def notes(factory):
    with factory() as s:
        return s.query(Note).count()


def test_first_sync_imports_everything_and_later_syncs_do_nothing(env):
    sync, mgr, folder, factory = env
    r1 = sync.run_once()
    assert r1["files"] == 2 and r1["new"] == 2 and r1["problem"] is None
    settle(mgr)
    assert notes(factory) == 2
    r2 = sync.run_once()
    assert r2["new"] == 0 and sync.status()["pending"] == 0
    assert all((folder / n).exists() for n in os.listdir(folder))        # originals untouched


def test_a_new_recording_is_picked_up_on_the_next_check(env):
    sync, mgr, folder, factory = env
    sync.run_once(); settle(mgr)
    (folder / "20260103 090000-CCC.m4a").write_bytes(b"groceries milk eggs")
    r = sync.run_once()
    assert r["new"] == 1
    settle(mgr)
    assert notes(factory) == 3


def test_files_still_importing_are_not_submitted_twice(env):
    sync, mgr, folder, factory = env
    a = sync.run_once()
    b = sync.run_once()        # straight away: the same files are in flight or already done
    assert a["new"] == 2 and b["new"] == 0
    settle(mgr)
    assert notes(factory) == 2


def test_failures_are_retried_a_few_times_then_given_up_on(env):
    sync, mgr, folder, factory = env
    (folder / "20260104 090000-BAD.m4a").write_bytes(b"corrupt")
    sync.run_once(); settle(mgr)
    assert notes(factory) == 3  # the bad file still became a note row, but its processing failed
    for _ in range(MAX_FAILURES - 1):
        r = sync.run_once()
        assert r["new"] == 1    # retried
        settle(mgr)
    assert sync.run_once()["new"] == 0   # after MAX_FAILURES it stops retrying
    assert sync.state["failures"][str(folder / "20260104 090000-BAD.m4a")] == MAX_FAILURES


def test_a_recording_edited_after_import_is_reported_not_reimported(env):
    sync, mgr, folder, factory = env
    sync.run_once(); settle(mgr)
    target = folder / "20260101 090000-AAA.m4a"
    target.write_bytes(b"baby giggling in the bath, trimmed and much longer now")
    r = sync.run_once()
    assert r["new"] == 0 and r["changed"] == 1 and sync.status()["changed"] == 1
    settle(mgr)
    assert notes(factory) == 2          # no duplicate note


def test_a_blocked_or_missing_folder_is_a_problem_not_a_crash(env, monkeypatch, tmp_path):
    sync, mgr, folder, factory = env

    def blocked(f, limit=5000):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(sync_mod, "audio_files", blocked)
    r = sync.run_once()
    assert r["problem"] == PERMISSION_HELP and sync.status()["problem"] == PERMISSION_HELP
    monkeypatch.undo()
    gone = SyncManager(mgr, tmp_path / "s2", source_resolver=lambda s: (None, "I couldn't find the Voice Memos library"))
    assert "couldn't find" in gone.run_once()["problem"]
    assert sync.run_once()["problem"] is None         # and it recovers when access is fixed


def test_icloud_only_recordings_are_counted(tmp_path):
    f = tmp_path / "vm"
    f.mkdir()
    (f / ".20260105 090000-DDD.m4a.icloud").write_bytes(b"stub")
    (f / "real.m4a").write_bytes(b"x")
    (f / ".hidden.txt").write_text("x")
    assert icloud_placeholders(f) == 1


def test_voice_memos_source_reports_placeholders(env, tmp_path):
    sync, mgr, folder, factory = env
    (folder / ".20260105 090000-EEE.m4a.icloud").write_bytes(b"stub")
    sync.settings["source"] = "voice_memos"
    assert sync.run_once()["placeholders"] == 1


def test_settings_persist_across_restarts_and_are_validated(env, tmp_path):
    sync, mgr, folder, factory = env
    st = sync.set_settings(enabled=True, interval_min=30)
    assert st["enabled"] is True and st["interval_min"] == 30
    sync.stop()
    again = SyncManager(mgr, tmp_path / "state", source_resolver=lambda s: (folder, None))
    assert again.settings["enabled"] is True and again.settings["interval_min"] == 30
    for bad in (0, 1441, -5):
        with pytest.raises(ValueError):
            sync.set_settings(interval_min=bad)
    again.stop()


def test_sync_is_off_until_the_user_turns_it_on(env):
    sync, mgr, folder, factory = env
    assert sync.settings["enabled"] is False
    time.sleep(0.2)
    assert notes(factory) == 0          # nothing happens by itself


def test_the_background_thread_syncs_new_files_on_its_own(tmp_path):
    folder = tmp_path / "vm"
    folder.mkdir()
    factory = make_session_factory(tmp_path / "lib.db")
    holder = {}
    mgr = ImportManager(factory, tmp_path / "audio", Deps(Flaky(), FakeEnricher(), FakeEmbedder()),
                        on_file_done=lambda f: holder["sync"].on_file_done(f))
    sync = holder["sync"] = SyncManager(mgr, tmp_path / "state", source_resolver=lambda s: (folder, None), poll_seconds=0.1)
    sync.set_settings(enabled=True)
    (folder / "a.m4a").write_bytes(b"baby giggling")
    deadline = time.time() + 8
    while time.time() < deadline and notes(factory) < 1:
        time.sleep(0.1)
    sync.stop()
    assert notes(factory) == 1 and sync.status()["last"]["problem"] is None


# ---------- API ----------

def test_sync_api(env, tmp_path):
    sync, mgr, folder, factory = env
    c = TestClient(create_app(factory, embedder=FakeEmbedder(), import_manager=mgr, upload_dir=tmp_path / "up", sync_manager=sync))
    s = c.get("/api/sync").json()
    assert s["available"] is True and s["enabled"] is False and s["pending"] == 0
    on = c.post("/api/sync/settings", json={"enabled": True, "interval_min": 5}).json()
    assert on["enabled"] is True and on["interval_min"] == 5
    assert c.post("/api/sync/settings", json={"interval_min": 0}).status_code == 400
    deadline = time.time() + 8
    while time.time() < deadline and notes(factory) < 2:
        time.sleep(0.1)
    assert notes(factory) == 2                                    # turning it on ran a first check
    assert c.post("/api/sync/run").json()["available"] is True
    sync.stop()


def test_sync_api_unavailable_without_a_manager(tmp_path):
    c = TestClient(create_app(make_session_factory(tmp_path / "x.db")))
    assert c.get("/api/sync").json() == {"available": False}
    assert c.post("/api/sync/run").status_code == 503
    assert c.post("/api/sync/settings", json={"enabled": True}).status_code == 503


def test_sync_leaves_long_recordings_alone(env, monkeypatch):
    import vl.batch as b
    sync, mgr, folder, factory = env
    lens = {"20260101 090000-AAA.m4a": 120.0, "20260102 090000-BBB.m4a": 70 * 60.0}
    monkeypatch.setattr(b, "probe_duration", lambda p: lens[p.name])
    sync._max_minutes = 45
    found = sync.run_once()
    assert found["new"] == 1 and found["too_long"] == 1
    settle(mgr)
    assert notes(factory) == 1                      # only the short one was imported
    sync._max_minutes = 0                           # raise the limit: the long one is picked up on the next check
    assert sync.run_once()["new"] == 1
    settle(mgr)
    assert notes(factory) == 2
