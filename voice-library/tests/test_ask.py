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


def test_rerank_drops_results_claude_did_not_endorse(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    first = ask(s, "q", FakeParser(sq), m, today=TODAY).hits[0].note_id
    res = ask(s, "q", FakeParser(sq), m, FakeReranker(order=[first]), today=TODAY)
    assert [h.note_id for h in res.hits] == [first] and res.hits[0].why
    assert any("set aside 1 weaker" in n for n in res.notes)


def test_rerank_endorsing_nothing_keeps_search_order(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    base = ask(s, "q", FakeParser(sq), m, today=TODAY).hits
    res = ask(s, "q", FakeParser(sq), m, FakeReranker(order=[999]), today=TODAY)  # an id that isn't a candidate
    assert [h.note_id for h in res.hits] == [h.note_id for h in base] and len(res.hits) == 2
    assert any("plain search order" in n for n in res.notes)


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
    assert parse_rerank(raw, {1, 2}) == [{"id": 1, "why": "a", "strength": None}]


# --- match strength labels and the verdict line ---

from vl.ask import verdict_for
from vl.index.search import Hit


class Labeller:
    """Returns the candidates in the given order with the given strength per note NAME."""

    def __init__(self, session, strengths, order=None):
        self.session, self.strengths, self.order = session, strengths, order

    def rerank(self, question, candidates):
        from vl.db import Note
        ids = self.order or [c["id"] for c in candidates]
        out = []
        for i in ids:
            name = self.session.get(Note, i).original_name
            out.append({"id": i, "why": f"why {name}", "strength": self.strengths.get(name)})
        return out


def _hit(strength):
    return Hit(note_id=1, title="t", summary="s", category=None, recorded_at=None, path="p", score=0.0, strength=strength)


@pytest.mark.parametrize("strengths, expected", [
    (["match", "partial"], "One clear match."),
    (["match", "match", "related"], "2 likely matches."),
    (["partial", "related"], "No clear match; these only partly match."),
    (["related", "related"], "No clear match; these are only loosely related."),
    ([None, None], None), ([], None)])
def test_verdict_is_computed_from_labels(strengths, expected):
    assert verdict_for([_hit(x) for x in strengths]) == expected


def test_strongest_label_goes_first_even_if_claude_listed_it_later(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    IDEA, BABY = "20241103 101530.m4a", "20260801 090000.m4a"
    # Claude lists the BABY note first but calls it only "related"; the IDEA note is the "match"
    from vl.db import Note
    ids = {n.original_name: n.id for n in s.query(Note)}
    rr = Labeller(s, {BABY: "related", IDEA: "match"}, order=[ids[BABY], ids[IDEA]])
    res = ask(s, "q", FakeParser(sq), m, rr, today=TODAY)
    assert [h.strength for h in res.hits] == ["match", "related"]
    assert s.get(Note, res.hits[0].note_id).original_name == IDEA
    assert res.verdict == "One clear match."


def test_no_labels_means_no_verdict_and_no_badge(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    res = ask(s, "q", FakeParser(sq), m, FakeReranker(), today=TODAY)  # FakeReranker gives no strengths
    assert res.verdict is None and all(h.strength is None for h in res.hits)


def test_rerank_failure_or_no_reranker_gives_no_verdict(lib):
    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    assert ask(s, "q", FakeParser(sq), m, FakeReranker(boom=True), today=TODAY).verdict is None
    assert ask(s, "q", FakeParser(sq), m, None, today=TODAY).verdict is None


def test_parse_rerank_normalizes_strength():
    raw = ('[{"id":1,"strength":"MATCH","why":"a"},{"id":2,"strength":"definitely","why":"b"},'
           '{"id":3,"why":"c"}]')
    got = parse_rerank(raw, {1, 2, 3})
    assert [g["strength"] for g in got] == ["match", None, None]


def test_cli_output_shows_badge_verdict_and_reason(lib):
    """Checks the real printing code (format_ask_result) end to end with fakes."""
    from vl.cli import format_ask_result

    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    rr = Labeller(s, {"20260801 090000.m4a": "match", "20241103 101530.m4a": "related"})
    out = format_ask_result(ask(s, "q", FakeParser(sq), m, rr, today=TODAY))
    lines = out.splitlines()
    assert "Result: One clear match." in lines
    first = next(l for l in lines if l.startswith("1. "))
    second = next(l for l in lines if l.startswith("2. "))
    assert "<MATCH>" in first and "<related>" in second
    assert any(l.strip().startswith("why: why ") for l in lines)


def test_cli_output_has_no_badge_or_result_line_without_labels(lib):
    from vl.cli import format_ask_result

    s, m = lib
    sq = StructuredQuery(semantic_text="baby idea app", keywords=["baby", "idea", "app"])
    out = format_ask_result(ask(s, "q", FakeParser(sq), m, None, today=TODAY))
    assert "<" not in out and "Result:" not in out and "1. " in out
