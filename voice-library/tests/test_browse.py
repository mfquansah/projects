import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from vl import library as lib
from vl.api.main import create_app
from vl.db import Category, DeletedNote, Enrichment, Note, NoteFlag, make_session_factory

from tests.conftest import FakeEmbedder


def add(s, i, title, when, secs, tags=(), cat=None):
    n = Note(sha256=f"{i:064d}", path=f"/x/{i}.m4a", original_name=f"n{i}.m4a", recorded_at=when, duration_s=secs, date_source="filename")
    s.add(n)
    s.flush()
    s.add(Enrichment(note_id=n.id, title=title, summary=f"about {title}", category_id=cat, tags_json=json.dumps(list(tags)),
                     junk_score=0, model_version="t"))
    s.commit()
    return n.id


@pytest.fixture
def s(tmp_path):
    factory = make_session_factory(tmp_path / "t.db")
    with factory() as session:
        fam = session.query(Category).filter_by(name="Family memories").one().id
        add(session, 1, "Bike ride", dt.datetime(2026, 10, 3, 17, 0), 14, ["bike", "kids"], fam)
        add(session, 2, "Team meeting", dt.datetime(2026, 11, 1, 9, 0), 3000, ["meeting"], None)
        add(session, 3, "Lullaby", dt.datetime(2026, 11, 15, 22, 0), 95, ["lullaby", "kids"], fam)
        add(session, 4, "apple idea", dt.datetime(2026, 11, 18, 8, 0), 600, ["idea"], None)
        add(session, 5, "Unknown length", dt.datetime(2026, 9, 1, 8, 0), None, [], None)
        session.fam = fam
        yield session


def titles(res):
    return [h.title for h in res[0]]


def test_sorts_with_unknown_lengths_last(s):
    assert titles(lib.browse_notes(s, sort="newest"))[:2] == ["apple idea", "Lullaby"]
    assert titles(lib.browse_notes(s, sort="oldest"))[:2] == ["Unknown length", "Bike ride"]
    assert titles(lib.browse_notes(s, sort="longest")) == ["Team meeting", "apple idea", "Lullaby", "Bike ride", "Unknown length"]
    assert titles(lib.browse_notes(s, sort="shortest")) == ["Bike ride", "Lullaby", "apple idea", "Team meeting", "Unknown length"]
    assert titles(lib.browse_notes(s, sort="title")) == ["apple idea", "Bike ride", "Lullaby", "Team meeting", "Unknown length"]   # case-insensitive
    with pytest.raises(ValueError):
        lib.browse_notes(s, sort="sideways")


def test_filters_combine_and_total_counts_all_matches(s):
    assert lib.browse_notes(s)[1] == 5
    hits, total = lib.browse_notes(s, category_id=s.fam)
    assert total == 2 and {h.title for h in hits} == {"Bike ride", "Lullaby"}
    assert titles(lib.browse_notes(s, since="2026-11-01", until="2026-11-15")) == ["Lullaby", "Team meeting"]    # both ends inclusive
    assert lib.browse_notes(s, min_s=60, max_s=900)[1] == 2                                                   # unknown length excluded
    assert titles(lib.browse_notes(s, tag="kids", sort="oldest")) == ["Bike ride", "Lullaby"]
    assert lib.browse_notes(s, tag="KIDS ")[1] == 2                                                           # case and spaces forgiven
    assert lib.browse_notes(s, tag="ki")[1] == 0                                                              # whole tags only
    assert lib.browse_notes(s, tag="100%")[1] == 0                                                            # wildcard characters are literal
    assert titles(lib.browse_notes(s, category_id=s.fam, since="2026-11-01", tag="kids")) == ["Lullaby"]
    with pytest.raises(ValueError):
        lib.browse_notes(s, since="yesterday")


def test_paging_and_archived_notes_are_left_out(s):
    page1, total = lib.browse_notes(s, sort="oldest", limit=2, offset=0)
    page2, _ = lib.browse_notes(s, sort="oldest", limit=2, offset=2)
    assert total == 5 and len(page1) == 2 and len(page2) == 2 and not {h.note_id for h in page1} & {h.note_id for h in page2}
    s.add(NoteFlag(note_id=page1[0].note_id, flag="archived"))
    s.commit()
    assert lib.browse_notes(s)[1] == 4


def test_bulk_archive_and_delete(s, tmp_path):
    audio = tmp_path / "audio"
    audio.mkdir()
    (audio / "x").write_text("keep")
    out = lib.bulk_action(s, "archive", [1, 2, 2, 999])
    assert out["done"] == 2 and out["failed"] == [{"id": 999, "error": "No such note."}]
    assert lib.browse_notes(s)[1] == 3
    out = lib.bulk_action(s, "delete", [3, 4], audio, None)
    assert out["done"] == 2 and s.get(Note, 3) is None and s.get(Note, 4) is None
    assert s.query(DeletedNote).count() == 2
    with pytest.raises(ValueError):
        lib.bulk_action(s, "explode", [1])


def test_api_browse_tags_and_bulk(tmp_path):
    factory = make_session_factory(tmp_path / "t.db")
    with factory() as session:
        add(session, 1, "Bike ride", dt.datetime(2026, 10, 3), 14, ["bike"])
        add(session, 2, "Lullaby", dt.datetime(2026, 11, 15), 95, ["lullaby", "bike"])
    c = TestClient(create_app(factory, embedder=FakeEmbedder(), audio_root=tmp_path / "audio"))
    r = c.get("/api/browse?sort=longest&limit=1").json()
    assert r["total"] == 2 and [h["title"] for h in r["hits"]] == ["Lullaby"]
    assert c.get("/api/browse?tag=lullaby").json()["total"] == 1
    assert c.get("/api/browse?min_length=60").json()["total"] == 1
    assert c.get("/api/browse?sort=nope").status_code == 400
    assert c.get("/api/browse?since=yesterday").status_code == 400
    assert c.get("/api/browse?min_length=-5").status_code == 422
    assert c.get("/api/tags").json()["tags"][0] == {"tag": "bike", "count": 2}
    assert c.post("/api/notes/bulk", json={"action": "archive", "ids": []}).status_code == 422
    assert c.post("/api/notes/bulk", json={"action": "explode", "ids": [1]}).status_code == 400
    assert c.post("/api/notes/bulk", json={"action": "archive", "ids": [1]}).json() == {"done": 1, "failed": []}
    assert c.get("/api/browse").json()["total"] == 1
    r = c.post("/api/notes/bulk", json={"action": "delete", "ids": [2, 77]}).json()
    assert r["done"] == 1 and r["failed"][0]["id"] == 77
