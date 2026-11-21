import json

import pytest

from vl.ask import ask
from vl.eval import (
    Counting, EvalSetError, Question, check_expected_exist, format_report, load_questions, run_mode, to_json,
)
from vl.index.search import search
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes
from vl.enrich.query import StructuredQuery

IDEA = "20241103 101530.m4a"   # "my idea for a better app name called Echo"
BABY = "20260801 090000.m4a"   # "baby laughing at the dog this morning so cute"


@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    return session, m


def write(tmp_path, obj):
    p = tmp_path / "q.json"
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
    return p


def test_load_valid(tmp_path):
    qs = load_questions(write(tmp_path, {"questions": [
        {"q": " app name ", "kind": "content", "expect": [IDEA]},
        {"q": "pizza", "kind": "none", "expect": []},
        {"q": "no kind given", "expect": [BABY]},
    ]}))
    assert [q.q for q in qs] == ["app name", "pizza", "no kind given"]
    assert qs[2].kind == "content"


@pytest.mark.parametrize("bad, fragment", [
    ("{not json", "not valid JSON"),
    ({"questions": []}, "at least one"),
    ([], "at least one"),
    ({"questions": [{"q": "", "expect": ["a"]}]}, 'non-empty "q"'),
    ({"questions": [{"q": "x", "expect": "a.m4a"}]}, "list of filenames"),
    ({"questions": [{"q": "x", "kind": "content", "expect": []}]}, "at least one expected"),
    ({"questions": [{"q": "x", "kind": "none", "expect": ["a.m4a"]}]}, "empty"),
])
def test_load_rejects_bad_files(tmp_path, bad, fragment):
    with pytest.raises(EvalSetError, match=fragment):
        load_questions(write(tmp_path, bad))


def test_typo_in_expected_name_fails_loudly(lib):
    s, _ = lib
    check_expected_exist(s, [Question("q", "content", [IDEA.upper()])])  # case-insensitive is fine
    with pytest.raises(EvalSetError) as e:
        check_expected_exist(s, [Question("q", "content", ["Nope.m4a"])])
    assert "Nope.m4a" in str(e.value)


def test_scoring_ranks_and_metrics(lib):
    s, m = lib
    qs = [
        Question("my idea app name Echo", "content", [IDEA]),         # keyword hit -> rank 1
        Question("baby laughing dog", "content", [BABY]),             # rank 1
        Question("baby laughing dog", "content", [IDEA]),             # wrong answer expected -> rank 2 or miss
        Question("zzzz qqqq", "none", []),                            # correctly empty
        Question("baby", "none", []),                                 # false positive
    ]
    rep = run_mode(s, "search", lambda q: (search(s, q, m, limit=5), []), qs)
    r = rep.results
    assert r[0].rank == 1 and r[1].rank == 1
    assert r[2].rank in (None, 2, 3, 4, 5)
    assert r[3].correct_empty and not r[4].correct_empty and r[4].returned
    assert rep.hit_at(1) == pytest.approx(2 / 3)      # none-questions excluded from hit@k
    assert rep.empty_score() == (1, 2)
    assert 0 < rep.mrr() <= 1
    text = format_report([rep])
    assert "FALSE POSITIVE" in text and "search" in text


def test_a_crashing_question_is_recorded_not_fatal(lib):
    s, _ = lib

    def runner(q):
        if q == "boom":
            raise RuntimeError("api down")
        return [], []

    rep = run_mode(s, "x", runner, [Question("boom", "content", [IDEA]), Question("fine", "none", [])])
    assert rep.results[0].error == "RuntimeError: api down" and rep.results[0].rank is None
    assert rep.results[1].correct_empty
    assert "ERROR on 'boom'" in format_report([rep])


class _P:
    def parse(self, question, categories, today):
        return StructuredQuery(semantic_text=question, keywords=question.split())


class _R:
    def rerank(self, question, candidates):
        return [{"id": c["id"], "why": "w"} for c in candidates][::-1]


def test_modes_and_llm_call_counting(lib):
    s, m = lib
    qs = [Question("baby laughing dog", "content", [BABY]), Question("idea app name", "content", [IDEA])]
    p, r = Counting(_P(), "parse"), Counting(_R(), "rerank")
    rep = run_mode(s, "ask", lambda q: (lambda a: (a.hits, a.notes))(ask(s, q, p, m, r)), qs)
    assert p.calls == 2 and r.calls <= 2 and rep.results[0].rank is not None


def test_json_output_roundtrips(lib):
    s, m = lib
    rep = run_mode(s, "search", lambda q: (search(s, q, m), []), [Question("baby", "content", [BABY])])
    data = json.loads(to_json([rep], "questions.json"))
    assert data["summary"][0]["mode"] == "search" and data["results"]["search"][0]["q"] == "baby"
