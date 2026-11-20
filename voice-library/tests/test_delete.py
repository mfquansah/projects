import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from vl import library as lib
from vl.api.main import create_app
from vl.batch import pick_new
from vl.db import DeletedNote, Embedding, Enrichment, Note, NoteFlag, SoundEvent, Transcript, make_session_factory
from vl.ingest.importer import DeletedEarlier, import_folder, import_one
from vl.jobs import Deps, ImportManager
from vl.pipeline import ProcessResult, process_note

from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


@pytest.fixture
def env(tmp_path):
    folder = tmp_path / "vm"
    folder.mkdir()
    a, b = folder / "20261101 100000.m4a", folder / "20261102 100000.m4a"
    a.write_bytes(b"baby laughing in the bath")
    b.write_bytes(b"my work meeting notes")
    factory = make_session_factory(tmp_path / "t.db")
    return {"tmp": tmp_path, "folder": folder, "a": a, "b": b, "factory": factory, "audio": tmp_path / "audio"}


def full_note(env, path):
    """Import a file and run every stage, like the real pipeline."""
    with env["factory"]() as s:
        note, _ = import_one(s, path, env["audio"])
        process_note(s, note, FakeTranscriber(), FakeEnricher(), FakeEmbedder(), ProcessResult())
        s.add(SoundEvent(note_id=note.id, label="baby_laugh", start_s=0, end_s=5, confidence=0.9, model_version="x"))
        s.merge(NoteFlag(note_id=note.id, flag="keep"))
        s.commit()
        return note.id, Path(note.path), note.sha256


def test_delete_removes_everything_and_leaves_the_original(env):
    nid, audio_copy, sha = full_note(env, env["a"])
    keep_id, keep_copy, _ = full_note(env, env["b"])
    cache = env["tmp"] / "peaks"
    cache.mkdir()
    (cache / f"{sha[:32]}-96.json").write_text("[]")
    assert audio_copy.is_file()
    with env["factory"]() as s:
        out = lib.delete_note(s, nid, env["audio"], cache)
        assert out == {"deleted": True, "audio_removed": True}
        assert s.get(Note, nid) is None
        for model in (Transcript, Enrichment, Embedding, SoundEvent, NoteFlag):
            assert s.query(model).filter_by(note_id=nid).count() == 0
        assert s.execute(text("SELECT count(*) FROM notes_fts WHERE note_id = :i"), {"i": nid}).scalar() == 0
        assert s.get(DeletedNote, sha) is not None
        assert s.get(Note, keep_id) is not None          # the other recording is untouched
    assert not audio_copy.exists() and keep_copy.exists()
    assert env["a"].exists()                              # the original is never touched
    assert not list(cache.glob("*.json"))


def test_delete_never_removes_files_outside_the_audio_folder(env):
    with env["factory"]() as s:
        note, _ = import_one(s, env["a"], env["audio"])
        outside = env["tmp"] / "precious.m4a"
        outside.write_bytes(b"do not delete")
        note.path = str(outside)
        s.commit()
        out = lib.delete_note(s, note.id, env["audio"], None)
    assert out["audio_removed"] is False and outside.exists()


def test_delete_unknown_note_raises(env):
    with env["factory"]() as s, pytest.raises(ValueError):
        lib.delete_note(s, 999, env["audio"], None)


def test_a_deleted_recording_is_not_imported_again(env):
    nid, _, _ = full_note(env, env["a"])
    with env["factory"]() as s:
        lib.delete_note(s, nid, env["audio"], None)
        with pytest.raises(DeletedEarlier):
            import_one(s, env["a"], env["audio"])
        r = import_folder(s, env["folder"], env["audio"])
        assert r.added == 1 and r.skipped == 1                # only the other recording came in
        assert s.query(Note).count() == 1                      # just the other recording
        # the "next N" picker offers the other recording (imported but not processed yet), never the deleted one
        assert [p.name for p in pick_new([env["a"], env["b"]], 5, s)] == ["20261102 100000.m4a"]


def test_import_job_marks_it_removed(env):
    nid, _, _ = full_note(env, env["a"])
    with env["factory"]() as s:
        lib.delete_note(s, nid, env["audio"], None)
    mgr = ImportManager(env["factory"], env["audio"], Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder()))
    job = mgr.submit([("20261101 100000.m4a", env["a"], None, False)])
    assert mgr.wait(10)
    snap = mgr.snapshot(job)
    assert snap["files"][0]["state"] == "removed" and snap["removed"] == 1 and snap["finished"] is True
    assert snap["done"] == 0 and snap["errors"] == 0


def test_api_delete_then_gone(env):
    mgr = ImportManager(env["factory"], env["audio"], Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder()))
    c = TestClient(create_app(env["factory"], embedder=FakeEmbedder(), audio_root=env["audio"], import_manager=mgr,
                              cache_dir=env["tmp"] / "peaks", upload_dir=env["tmp"] / "up"))
    nid, audio_copy, _ = full_note(env, env["a"])
    assert c.get(f"/api/notes/{nid}").status_code == 200
    r = c.delete(f"/api/notes/{nid}")
    assert r.status_code == 200 and r.json() == {"deleted": True, "audio_removed": True}
    assert c.get(f"/api/notes/{nid}").status_code == 404
    assert c.delete(f"/api/notes/{nid}").status_code == 404
    assert not audio_copy.exists()
    # importing the same folder again skips the deleted recording and says so
    r2 = c.post("/api/import/folder", json={"path": str(env["folder"])}).json()
    assert mgr.wait(10)
    snap = c.get(f"/api/import/{r2['job_id']}").json()
    states = {f["name"]: f["state"] for f in snap["files"]}
    assert states["20261101 100000.m4a"] == "removed"
