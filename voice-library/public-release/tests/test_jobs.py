import datetime as dt
from pathlib import Path

import pytest

from vl.db import Enrichment, Note, SoundEvent, Status, make_session_factory
from vl.jobs import Deps, ImportManager
from vl.sounds.tagger import SoundHit

from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


class Tagger:
    model_version = "fake-ast"

    def __init__(self, boom=False):
        self.boom = boom

    def tag(self, path):
        if self.boom:
            raise RuntimeError("model crashed")
        return [SoundHit("baby_babble", 1.0, 5.0, 0.8)]


@pytest.fixture
def setup(tmp_path):
    factory = make_session_factory(tmp_path / "j.db")
    uploads = tmp_path / "up"
    uploads.mkdir()

    def make(name, text):
        p = uploads / name
        p.write_bytes(text.encode())
        return (name, p, None)

    return factory, tmp_path / "audio", make


def manager(factory, store, **kw):
    deps = Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder(), kw.get("tagger"))
    return ImportManager(factory, store, kw.get("deps", deps))


def test_files_flow_through_every_stage_and_end_up_searchable(setup):
    factory, store, make = setup
    m = manager(factory, store, tagger=Tagger())
    jid = m.submit([make("a.m4a", "baby laughing at the dog"), make("b.m4a", "my idea for an app")])
    assert m.wait()
    snap = m.snapshot(jid)
    assert snap["finished"] and snap["done"] == 2 and snap["errors"] == 0
    assert [f["state"] for f in snap["files"]] == ["done", "done"]
    assert {f["category"] for f in snap["files"]} == {"Family memories", "Ideas"}
    with factory() as s:
        assert s.query(Note).count() == 2 and s.query(SoundEvent).count() == 2
        from vl.index.search import search
        assert search(s, "dog", FakeEmbedder())  # imported => indexed => findable
    assert not list(Path(setup[2]("tmp.m4a", "x")[1].parent).glob("a.m4a"))  # temp uploads are removed


def test_one_bad_file_does_not_stop_the_others_and_shows_its_error(setup):
    factory, store, make = setup

    class Flaky(FakeTranscriber):
        def transcribe(self, path, progress=None):
            if b"corrupt" in path.read_bytes():
                raise RuntimeError("cannot decode")
            return super().transcribe(path, progress)

    m = ImportManager(factory, store, Deps(Flaky(), FakeEnricher(), FakeEmbedder()))
    jid = m.submit([make("bad.m4a", "corrupt"), make("ok.m4a", "baby laughing")])
    assert m.wait()
    snap = m.snapshot(jid)
    assert [f["state"] for f in snap["files"]] == ["error", "done"] and snap["errors"] == 1
    assert "cannot decode" in snap["files"][0]["error"]


def test_duplicates_are_reported_not_reimported(setup):
    factory, store, make = setup
    m = manager(factory, store)
    m.submit([make("a.m4a", "same audio bytes")])
    assert m.wait()
    jid = m.submit([make("copy.m4a", "same audio bytes")])
    assert m.wait()
    f = m.snapshot(jid)["files"][0]
    assert f["state"] == "duplicate" and f["title"]
    with factory() as s:
        assert s.query(Note).count() == 1


def test_a_sound_failure_does_not_fail_the_import(setup):
    factory, store, make = setup
    m = manager(factory, store, tagger=Tagger(boom=True))
    jid = m.submit([make("a.m4a", "baby laughing")])
    assert m.wait()
    assert m.snapshot(jid)["files"][0]["state"] == "done"
    with factory() as s:
        assert s.query(Status).filter_by(stage="sounds", state="error").count() == 1


def test_models_load_lazily_once_and_a_failing_factory_marks_files_failed(setup):
    factory, store, make = setup
    calls = []

    def lazy():
        calls.append(1)
        return Deps(FakeTranscriber(), FakeEnricher(), FakeEmbedder())

    m = ImportManager(factory, store, lazy)
    assert calls == []  # nothing loaded until a file arrives
    m.submit([make("a.m4a", "baby"), make("b.m4a", "idea")])
    assert m.wait() and calls == [1]

    def broken():
        raise RuntimeError("no model installed")

    m2 = ImportManager(factory, store, broken)
    jid = m2.submit([make("c.m4a", "x")])
    assert m2.wait()
    f = m2.snapshot(jid)["files"][0]
    assert f["state"] == "error" and "no model installed" in f["error"]


def test_the_browsers_modified_time_is_only_a_last_resort_date(setup):
    factory, store, make = setup
    when = dt.datetime(2023, 5, 6, 12, 0, 0)
    name, path, _ = make("New Recording 9.m4a", "no date anywhere")
    name2, path2, _ = make("20240101 120000.m4a", "date in name")
    m = manager(factory, store)
    m.submit([(name, path, when), (name2, path2, when)])
    assert m.wait()
    with factory() as s:
        by = {n.original_name: n for n in s.query(Note)}
    assert by["New Recording 9.m4a"].recorded_at == when and by["New Recording 9.m4a"].date_source == "file-modified"
    assert by["20240101 120000.m4a"].date_source == "filename"  # the name wins over the browser time


def test_snapshot_counts_and_unknown_job(setup):
    factory, store, make = setup
    m = manager(factory, store)
    assert m.snapshot("nope") is None and m.latest() is None
    jid = m.submit([make("a.m4a", "x"), make("b.m4a", "y"), make("c.m4a", "z")])
    assert m.snapshot(jid)["total"] == 3
    assert m.wait()
    s = m.latest()
    assert s["id"] == jid and s["done"] == 3 and s["waiting"] == 0 and s["working"] == 0 and s["finished"]


def test_uploads_after_the_worker_went_idle_are_still_processed(setup):
    import time
    factory, store, make = setup
    m = manager(factory, store)
    m.submit([make("a.m4a", "first")])
    assert m.wait()
    time.sleep(1.4)  # longer than the worker's idle timeout: its thread has exited
    assert m._thread is None
    jid = m.submit([make("b.m4a", "second")])
    assert m.wait()
    assert m.snapshot(jid)["files"][0]["state"] == "done"
