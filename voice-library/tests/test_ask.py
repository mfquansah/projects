import datetime as dt

import pytest

from vl.ask import ask
from vl.enrich.query import StructuredQuery, parse_rerank, parse_structured
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes

CATS = ["Ideas", "Family memories", "Work & projects", "Personal reflections", "Other"]
TODAY = dt.date(2026, 11, 15)


@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    return session, m


class FakeParser:
    def __init__(self, sq=None, boom=False):
        self.sq, self.boom, self.seen = sq, boom, None

    def parse(self, question, categories, today):
        self.seen = (question, categories, today)
        if self.boom:
            raise RuntimeError("api down")
        return self.sq


def test_parser_receives_question_categories_and_today(lib):
    s, m = lib
    p = FakeParser(StructuredQuery(semantic_text="child laughing"))
    ask(s, "child laughing", p, m, today=TODAY)
    assert p.seen[0] == "child laughing" and "Family memories" in p.seen[1] and p.seen[2] == TODAY


def test_meaning_search_through_ask(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="my kid giggling", keywords=["giggling"])
    res = ask(s, "q", FakeParser(sq), m, today=TODAY)
    assert res.hits and res.hits[0].category == "Family memories"


def test_date_range_filters(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", since=dt.datetime(2026, 7, 1), until=dt.datetime(2026, 9, 1))
    res = ask(s, "q", FakeParser(sq), m, today=TODAY)
    assert {h.category for h in res.hits} == {"Family memories"} and not res.notes


def test_llm_failure_falls_back_to_plain_search_and_says_so(lib):
    s, m = lib
    res = ask(s, "baby laughing", FakeParser(boom=True), m, today=TODAY)
    assert res.hits and any("plain search" in n for n in res.notes)


def test_relaxes_category_then_dates_with_honest_notes(lib):
    s, m = lib
    wrong_cat = StructuredQuery(semantic_text="baby laughing", category="Work & projects")
    res = ask(s, "q", FakeParser(wrong_cat), m, today=TODAY)
    assert res.hits and any("all categories" in n for n in res.notes)

    wrong_dates = StructuredQuery(semantic_text="baby laughing", since=dt.datetime(2019, 1, 1),
                                  until=dt.datetime(2019, 2, 1))
    res = ask(s, "q", FakeParser(wrong_dates), m, today=TODAY)
    assert res.hits and any("all dates" in n for n in res.notes)


def test_no_matches_is_empty_not_error(lib):
    s, m = lib
    res = ask(s, "q", FakeParser(StructuredQuery(semantic_text="zzzz qqqq", keywords=["zzzz"])), m, today=TODAY)
    assert res.hits == []


class FakeReranker:
    def __init__(self, order=None, boom=False):
        self.order, self.boom = order, boom

    def rerank(self, question, candidates):
        if self.boom:
            raise RuntimeError("api down")
        ids = self.order or [c["id"] for c in candidates][::-1]
        return [{"id": i, "why": f"matches because {i}"} for i in ids]


def test_rerank_reorders_and_adds_why(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    base = ask(s, "q", FakeParser(sq), m, today=TODAY).hits
    assert len(base) == 2
    res = ask(s, "q", FakeParser(sq), m, FakeReranker(), today=TODAY)
    assert [h.note_id for h in res.hits] == [h.note_id for h in base][::-1]
    assert all(h.why for h in res.hits)


def test_rerank_failure_keeps_search_order(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    base = ask(s, "q", FakeParser(sq), m, today=TODAY).hits
    res = ask(s, "q", FakeParser(sq), m, FakeReranker(boom=True), today=TODAY)
    assert [h.note_id for h in res.hits] == [h.note_id for h in base]
    assert any("rerank" in n for n in res.notes)


def test_rerank_omitted_candidates_are_kept_not_dropped(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    first = ask(s, "q", FakeParser(sq), m, today=TODAY).hits[0].note_id
    res = ask(s, "q", FakeParser(sq), m, FakeReranker(order=[first]), today=TODAY)
    assert len(res.hits) == 2 and res.hits[0].why and res.hits[1].why is None


def test_parse_structured_validates_everything():
    raw = '''Here you go:
    {"semantic_text": "baby laughing", "keywords": ["Baby", "laugh", " "], "category": "Nonsense",
     "since": "2026-10-25", "until": "2026-11-08", "sound": "baby_laugh"}'''
    sq = parse_structured(raw, "q", CATS)
    assert sq.keywords == ["baby", "laugh"] and sq.category is None
    assert sq.since == dt.datetime(2026, 10, 25) and sq.until == dt.datetime(2026, 11, 8)
    assert sq.sound == "baby_laugh"
    assert any("Ignored unknown category" in n for n in sq.notes)
    assert not any("sound tagging" in n for n in sq.notes)  # the sound filter is applied later, by `ask`


def test_parse_structured_drops_bad_dates():
    bad_order = parse_structured('{"semantic_text":"x","since":"2026-05-01","until":"2026-01-01"}', "q", CATS)
    assert bad_order.since is None and bad_order.until is None and bad_order.notes
    garbage = parse_structured('{"semantic_text":"x","since":"last tuesday"}', "q", CATS)
    assert garbage.since is None and garbage.notes


def test_parse_structured_requires_json_and_defaults_to_question():
    with pytest.raises(ValueError):
        parse_structured("I can't help with that", "q", CATS)
    assert parse_structured("{}", "find my idea", CATS).semantic_text == "find my idea"


def test_parse_rerank_ignores_invented_and_duplicate_ids():
    raw = 'x [{"id": 1, "why": "a"}, {"id": 99, "why": "made up"}, {"id": 1, "why": "dup"}, {"nope": 2}]'
    assert parse_rerank(raw, {1, 2}) == [{"id": 1, "why": "a"}]
