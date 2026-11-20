import datetime as dt
import json

import pytest

from vl import library as lib_
from vl.ask import ask
from vl.db import Category, Enrichment, Note, NoteFlag
from vl.enrich.query import StructuredQuery
from vl.index.search import search
from vl.ingest.importer import import_folder
from vl.pipeline import accepted_category_names, process_notes

IDEA = "20241103 101530.m4a"
BABY = "20260801 090000.m4a"
TODAY = dt.date(2026, 11, 15)


@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    return session, m


def nid(s, name):
    return s.query(Note).filter_by(original_name=name).one().id


def enr(s, name):
    return s.get(Enrichment, nid(s, name))


def cat_name(s, name):
    e = enr(s, name)
    return s.get(Category, e.category_id).name if e.category_id else None


def test_category_counts_include_empty_categories_and_exclude_archived(lib):
    s, _ = lib
    counts = {c["name"]: c["count"] for c in lib_.category_counts(s)}
    assert counts["Ideas"] == 1 and counts["Family memories"] == 1 and counts["Work & projects"] == 0
    lib_.set_flag(s, nid(s, BABY), "archived")
    assert {c["name"]: c["count"] for c in lib_.category_counts(s)}["Family memories"] == 0


def test_suggestion_accept_creates_category_and_moves_notes(lib):
    s, _ = lib
    enr(s, IDEA).suggested_category = "Product naming"
    enr(s, BABY).suggested_category = "product  NAMING"  # spacing/case differences are the same suggestion
    s.commit()
    sug = lib_.suggested_categories(s)
    assert len(sug) == 1 and sug[0]["count"] == 2
    res = lib_.accept_suggestion(s, "Product naming")
    assert res["moved"] == 2
    assert cat_name(s, IDEA) == "Product naming" and cat_name(s, BABY) == "Product naming"
    assert enr(s, IDEA).suggested_category is None
    assert "Product naming" in accepted_category_names(s)  # Claude is offered it from now on
    assert lib_.suggested_categories(s) == []


def test_rejected_suggestion_is_remembered_and_not_offered_to_claude(lib):
    s, _ = lib
    enr(s, IDEA).suggested_category = "Songs"
    s.commit()
    assert lib_.reject_suggestion(s, "Songs") == 1
    assert enr(s, IDEA).suggested_category is None and cat_name(s, IDEA) == "Ideas"
    assert "Songs" not in accepted_category_names(s)
    # a later note suggesting the same name must not re-surface it
    enr(s, BABY).suggested_category = "songs"
    s.commit()
    assert lib_.suggested_categories(s) == []


def test_accepting_nonexistent_suggestion_is_an_error(lib):
    s, _ = lib
    with pytest.raises(ValueError, match="No notes are suggesting"):
        lib_.accept_suggestion(s, "Nothing")


def test_create_category_manually_and_validation(lib):
    s, _ = lib
    res = lib_.create_category(s, "  Voice   journal ")
    assert res["category"] == "Voice journal" and res["moved"] == 0
    for bad in ("", "   ", "x" * 81):
        with pytest.raises(ValueError, match="1-80"):
            lib_.create_category(s, bad)
    with pytest.raises(ValueError, match="already exists"):
        lib_.create_category(s, "voice journal")
    with pytest.raises(ValueError, match="already exists"):
        lib_.create_category(s, "ideas")  # seed categories are protected too


def test_promote_a_tag_to_a_category_moves_only_notes_with_that_tag(lib):
    s, _ = lib
    tags = {t["tag"]: t["count"] for t in lib_.tag_counts(s)}
    assert tags == {"baby": 1, "app": 1}
    res = lib_.create_category(s, "Baby", from_tag="baby")
    assert res["moved"] == 1
    assert cat_name(s, BABY) == "Baby" and cat_name(s, IDEA) == "Ideas"


def test_user_can_recreate_a_previously_rejected_category(lib):
    s, _ = lib
    enr(s, IDEA).suggested_category = "Songs"
    s.commit()
    lib_.reject_suggestion(s, "Songs")
    assert lib_.create_category(s, "Songs")["category"] == "Songs"
    assert "Songs" in accepted_category_names(s)


def test_assign_category_validates(lib):
    s, _ = lib
    family = s.query(Category).filter_by(name="Family memories").one().id
    lib_.assign_category(s, nid(s, IDEA), family)
    assert cat_name(s, IDEA) == "Family memories"
    with pytest.raises(ValueError, match="doesn't exist"):
        lib_.assign_category(s, nid(s, IDEA), 9999)
    lib_.assign_category(s, nid(s, IDEA), None)
    assert cat_name(s, IDEA) is None


def test_review_queue_orders_by_junk_and_skips_decided_notes(lib):
    s, _ = lib
    enr(s, IDEA).junk_score, enr(s, BABY).junk_score = 0.6, 0.9
    s.commit()
    q = lib_.review_queue(s)
    assert [r["id"] for r in q] == [nid(s, BABY), nid(s, IDEA)]
    lib_.set_flag(s, nid(s, BABY), "keep")
    assert [r["id"] for r in lib_.review_queue(s)] == [nid(s, IDEA)]
    assert lib_.review_queue(s, min_junk=0.95) == []


def test_archive_hides_from_search_ask_and_categories_but_keeps_everything(lib, tmp_path):
    s, m = lib
    baby_note = s.get(Note, nid(s, BABY))
    assert any(h.note_id == baby_note.id for h in search(s, "baby laughing", m))
    lib_.set_flag(s, baby_note.id, "archived")
    assert not any(h.note_id == baby_note.id for h in search(s, "baby laughing", m))
    # also hidden from natural-language and sorted/property answers
    class P:
        def __init__(self, **kw): self.sq = StructuredQuery(**{"semantic_text": "", **kw})
        def parse(self, *a): return self.sq
    for q in (P(semantic_text="baby laughing", keywords=["baby"]), P(sort="newest")):
        res = ask(s, "q", q, m, today=TODAY)
        assert baby_note.id not in [h.note_id for h in res.hits]
    # nothing is deleted: the row, the audio file and the transcript are all still there
    from pathlib import Path
    assert Path(baby_note.path).exists() and lib_.note_detail(s, baby_note.id)["transcript"]
    assert [a["id"] for a in lib_.archived_notes(s)] == [baby_note.id]
    # un-archiving brings it back
    lib_.clear_flag(s, baby_note.id)
    assert any(h.note_id == baby_note.id for h in search(s, "baby laughing", m))


def test_flag_validation(lib):
    s, _ = lib
    with pytest.raises(ValueError, match="Unknown flag"):
        lib_.set_flag(s, nid(s, IDEA), "delete")
    with pytest.raises(ValueError, match="No such note"):
        lib_.set_flag(s, 9999, "keep")
    assert s.query(NoteFlag).count() == 0


def test_note_detail_has_everything_the_page_needs(lib):
    s, _ = lib
    d = lib_.note_detail(s, nid(s, BABY))
    assert d["title"] and d["category"] == "Family memories" and d["tags"] == ["baby"]
    assert "baby laughing" in d["transcript"] and d["sounds"] == [] and d["flag"] is None
    assert lib_.note_detail(s, 9999) is None
