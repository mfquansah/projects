import datetime as dt

import pytest

from vl.ask import ask
from vl.db import Note, Transcript
from vl.enrich.query import StructuredQuery, parse_structured
from vl.index.search import effective_duration
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes

IDEA = "20241103 101530.m4a"   # older, set to 30 s
BABY = "20260801 090000.m4a"   # newer, set to 90 s
CATS = ["Ideas", "Family memories", "Work & projects", "Personal reflections", "Other"]
TODAY = dt.date(2026, 11, 15)


@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    notes = {n.original_name: n for n in session.query(Note)}
    notes[IDEA].duration_s, notes[BABY].duration_s = 30.0, 90.0
    session.commit()
    return session, m


class P:
    def __init__(self, **kw):
        self.sq = StructuredQuery(**{"semantic_text": "", **kw})

    def parse(self, q, c, t):
        return self.sq


def names(s, res):
    return [s.get(Note, h.note_id).original_name for h in res.hits]


@pytest.mark.parametrize("sort, expected_first", [
    ("longest", BABY), ("shortest", IDEA), ("newest", BABY), ("oldest", IDEA)])
def test_pure_property_sorts(lib, sort, expected_first):
    s, m = lib
    res = ask(s, "q", P(sort=sort), m, today=TODAY)
    assert names(s, res)[0] == expected_first and len(res.hits) == 2


def test_count_limits_results(lib):
    s, m = lib
    assert names(s, ask(s, "q", P(sort="longest", count=1), m, today=TODAY)) == [BABY]


def test_topic_is_matched_first_then_sorted(lib):
    s, m = lib
    res = ask(s, "q", P(sort="longest", semantic_text="idea app", keywords=["idea", "app"]), m, today=TODAY)
    assert names(s, res) == [IDEA]  # the longer baby note isn't about the topic, so it must not appear


def test_filters_apply_before_sorting(lib):
    s, m = lib
    assert names(s, ask(s, "q", P(sort="longest", category="Ideas"), m, today=TODAY)) == [IDEA]
    res = ask(s, "q", P(sort="longest", since=dt.datetime(2026, 1, 1), until=dt.datetime(2027, 1, 1)), m, today=TODAY)
    assert names(s, res) == [BABY]


def test_missing_lengths_are_reported_not_guessed(lib):
    s, m = lib
    notes = {n.original_name: n for n in s.query(Note)}
    notes[IDEA].duration_s = None
    s.get(Transcript, notes[IDEA].id).segments_json = "[]"  # no transcript timing either
    s.commit()
    res = ask(s, "q", P(sort="longest"), m, today=TODAY)
    assert names(s, res) == [BABY]
    assert any("no length on record" in n for n in res.notes)


def test_no_length_info_at_all_says_so(lib):
    s, m = lib
    for n in s.query(Note):
        n.duration_s = None
        s.get(Transcript, n.id).segments_json = "[]"
    s.commit()
    res = ask(s, "q", P(sort="longest"), m, today=TODAY)
    assert len(res.hits) == 2 and any("none of the matching notes" in n for n in res.notes)


def test_length_falls_back_to_transcript_timing(lib):
    s, _ = lib
    note = s.query(Note).filter_by(original_name=IDEA).one()
    note.duration_s = None
    s.get(Transcript, note.id).segments_json = '[{"start":0,"end":12.5,"text":"a"},{"start":12.5,"end":47.0,"text":"b"}]'
    s.commit()
    assert effective_duration(s, note) == 47.0
    s.get(Transcript, note.id).segments_json = "not json"
    assert effective_duration(s, note) is None


def test_sorted_results_are_never_reranked(lib):
    s, m = lib

    class Boom:
        def rerank(self, *a):
            raise AssertionError("rerank must not run on a sorted answer")

    res = ask(s, "q", P(sort="longest"), m, Boom(), today=TODAY)
    assert names(s, res)[0] == BABY


def test_parse_sort_and_count_validation():
    ok = parse_structured('{"semantic_text":"","sort":"Longest","count":3}', "my 3 longest", CATS)
    assert ok.sort == "longest" and ok.count == 3 and ok.semantic_text == ""
    bad = parse_structured('{"semantic_text":"x","sort":"loudest","count":999}', "q", CATS)
    assert bad.sort is None and bad.count is None and any("unknown sort" in n for n in bad.notes)
    assert parse_structured('{"count":"abc"}', "find my idea", CATS).count is None
    # no sort and no topic from the model -> fall back to the raw question
    assert parse_structured("{}", "find my idea", CATS).semantic_text == "find my idea"
