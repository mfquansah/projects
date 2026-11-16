import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import vl.api.main as api_main
from vl.api.main import create_app
from vl.db import Note, make_session_factory
from vl.jobs import Deps, ImportManager
from vl.voicememos import PERMISSION_HELP, audio_files, find_voice_memos

from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


def make_tree(root: Path):
    (root / "sub").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "b.m4a").write_bytes(b"baby giggling in the bath")
    (root / "sub" / "a.m4a").write_bytes(b"my idea for an app")
    (root / "sub" / "notes.txt").write_text("not audio")
    (root / ".hidden" / "secret.m4a").write_bytes(b"x")
    (root / ".dotfile.m4a").write_bytes(b"x")
    return root


# ---------- voicememos.py ----------

def test_audio_files_are_recursive_sorted_by_path_and_skip_hidden_and_non_audio(tmp_path):
    root = make_tree(tmp_path / "vm")
    got = audio_files(root)
    assert got == [root / "b.m4a", root / "sub" / "a.m4a"]   # sorted by full path; hidden folders/files and .txt skipped


def test_audio_files_respects_the_limit(tmp_path):
    root = make_tree(tmp_path / "vm")
    assert len(audio_files(root, limit=1)) == 1


def test_find_voice_memos_found_missing_and_blocked(tmp_path, monkeypatch):
    root = make_tree(tmp_path / "vm")
    ok = find_voice_memos([str(tmp_path / "nope"), str(root)])
    assert ok == {"found": True, "path": str(root), "count": 2, "problem": None}

    missing = find_voice_memos([str(tmp_path / "nope")])
    assert missing["found"] is False and missing["path"] is None and "couldn't find" in missing["problem"]

    def blocked(folder, limit=5000):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr("vl.voicememos.audio_files", blocked)
    b = find_voice_memos([str(root)])
    assert b["found"] is False and b["path"] == str(root) and b["problem"] == PERMISSION_HELP
    assert "Full Disk Access" in b["problem"]


# ---------- jobs: originals are never deleted ----------

@pytest.fixture
def mgr(tmp_path):
    factory = make_session_factory(tmp_path / "j.db")
    return factory, ImportManager(factory, tmp_path / "store", Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder())), tmp_path


def test_in_place_files_are_kept_but_uploads_are_cleaned_up(mgr):
    factory, m, tmp = mgr
    original = tmp / "original.m4a"
    original.write_bytes(b"baby laughing at the dog")
    upload = tmp / "upload.m4a"
    upload.write_bytes(b"my idea for an app")
    m.submit([("original.m4a", original, None, False), ("upload.m4a", upload, None)])
    assert m.wait()
    assert original.exists()          # read in place: never touched
    assert not upload.exists()        # a temporary upload: removed once the library has its copy
    with factory() as s:
        assert s.query(Note).count() == 2


# ---------- API ----------

@pytest.fixture
def client_env(tmp_path):
    factory = make_session_factory(tmp_path / "api.db")
    mgr = ImportManager(factory, tmp_path / "audio", Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder()))
    app = create_app(factory, embedder=FakeEmbedder(), audio_root=tmp_path / "audio", import_manager=mgr, upload_dir=tmp_path / "up")
    return TestClient(app), mgr, tmp_path, factory


def test_import_a_folder_by_path_reads_in_place(client_env):
    c, mgr, tmp, factory = client_env
    root = make_tree(tmp / "vm")
    r = c.post("/api/import/folder", json={"path": str(root)})
    assert r.status_code == 200 and r.json()["accepted"] == 2 and r.json()["folder"] == str(root)
    assert mgr.wait()
    snap = c.get(f"/api/import/{r.json()['job_id']}").json()
    assert snap["finished"] and snap["done"] == 2 and snap["errors"] == 0
    assert (root / "b.m4a").exists() and (root / "sub" / "a.m4a").exists()    # originals untouched
    assert c.get("/api/search", params={"q": "bath"}).json()["hits"]           # and they're searchable
    # importing the same folder again adds nothing
    again = c.post("/api/import/folder", json={"path": str(root)}).json()
    assert mgr.wait()
    assert c.get(f"/api/import/{again['job_id']}").json()["files"][0]["state"] == "duplicate"
    with factory() as s:
        assert s.query(Note).count() == 2


def test_folder_import_errors_are_clear(client_env, monkeypatch):
    c, _, tmp, _ = client_env
    assert c.post("/api/import/folder", json={}).status_code == 400
    assert c.post("/api/import/folder", json={"path": "  "}).status_code == 400
    r = c.post("/api/import/folder", json={"path": str(tmp / "nowhere")})
    assert r.status_code == 400 and "isn't a folder" in r.json()["detail"]
    (tmp / "empty").mkdir()
    (tmp / "empty" / "x.txt").write_text("hi")
    r = c.post("/api/import/folder", json={"path": str(tmp / "empty")})
    assert r.status_code == 400 and "No audio files" in r.json()["detail"]

    def blocked(folder, limit=5000):
        raise PermissionError("nope")

    monkeypatch.setattr(api_main, "audio_files", blocked)
    r = c.post("/api/import/folder", json={"path": str(tmp / "empty")})
    assert r.status_code == 403 and "Full Disk Access" in r.json()["detail"]


def test_voice_memos_source_reports_what_it_finds(client_env, monkeypatch, tmp_path):
    c, mgr, tmp, _ = client_env
    root = make_tree(tmp / "vm")
    monkeypatch.setattr(api_main, "find_voice_memos", lambda: {"found": True, "path": str(root), "count": 2, "problem": None})
    assert c.get("/api/import/sources").json() == {"voice_memos": {"found": True, "path": str(root), "count": 2, "problem": None}}
    r = c.post("/api/import/folder", json={"source": "voice_memos"})
    assert r.status_code == 200 and r.json()["accepted"] == 2 and mgr.wait()

    monkeypatch.setattr(api_main, "find_voice_memos", lambda: {"found": False, "path": "/x", "count": 0, "problem": "blocked!"})
    r = c.post("/api/import/folder", json={"source": "voice_memos"})
    assert r.status_code == 403 and r.json()["detail"] == "blocked!"
    monkeypatch.setattr(api_main, "find_voice_memos", lambda: {"found": False, "path": None, "count": 0, "problem": "not found"})
    assert c.post("/api/import/folder", json={"source": "voice_memos"}).status_code == 404


def test_folder_import_needs_an_import_manager(tmp_path):
    factory = make_session_factory(tmp_path / "x.db")
    c = TestClient(create_app(factory))
    assert c.post("/api/import/folder", json={"path": str(tmp_path)}).status_code == 503
