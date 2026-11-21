import datetime as dt
import json

import pytest

from vl.db import Note
from vl.eval import check_expected_exist, load_questions
from vl.evalgen import (
    ClaudeQuestionWriter, absent_questions, content_questions, property_questions, review,
)
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes

IDEA = "20241103 101530.m4a"
BABY = "20260801 090000.m4a"


@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    return session


class FakeWriter:
    def __init__(self, boom_on=None):
        self.boom_on, self.seen = boom_on, []

    def write(self, title, summary, transcript, n):
        self.seen.append(transcript)
        if self.boom_on and self.boom_on in transcript:
            raise RuntimeError("api down")
        return [f"vague memory {i} of: {title}" for i in range(n)]


def test_content_questions_point_at_their_own_note(lib):
    qs, problems = content_questions(lib, FakeWriter(), per_note=2)
    assert problems == [] and len(qs) == 4
    by_expect = {}
    for q in qs:
        assert q["kind"] == "content" and len(q["expect"]) == 1 and q["check"]
        by_expect.setdefault(q["expect"][0], []).append(q)
    assert set(by_expect) == {IDEA, BABY} and all(len(v) == 2 for v in by_expect.values())


def test_one_failing_note_is_reported_not_fatal(lib):
    qs, problems = content_questions(lib, FakeWriter(boom_on="baby"), per_note=1)
    assert len(qs) == 1 and qs[0]["expect"] == [IDEA]
    assert len(problems) == 1 and "api down" in problems[0]


def test_max_notes_limits_calls(lib):
    w = FakeWriter()
    content_questions(lib, w, per_note=1, max_notes=1)
    assert len(w.seen) == 1


def test_property_questions_come_from_library_data(lib):
    notes = {n.original_name: n for n in lib.query(Note)}
    notes[IDEA].duration_s, notes[BABY].duration_s = 30.0, 90.0
    lib.commit()
    qs, skipped = property_questions(lib)
    by_q = {q["q"]: q for q in qs}
    assert by_q["my longest voice note"]["expect"] == [BABY]
    assert by_q["my shortest voice note"]["expect"] == [IDEA]
    assert by_q["my most recent voice note"]["expect"] == [BABY]
    assert by_q["my oldest voice note"]["expect"] == [IDEA]
    month = next(q for q in qs if q["kind"] == "date")
    assert month["q"] in ("voice notes from November 2024", "voice notes from August 2026") and len(month["expect"]) == 1
    assert skipped == []


def test_property_questions_skip_what_cant_be_known(lib):
    qs, skipped = property_questions(lib)  # fixtures have no durations (no mutagen on fake audio)
    assert not any("longest" in q["q"] for q in qs)
    assert any("durations" in s for s in skipped)


def test_absent_topics_are_verified_absent(lib):
    texts = [q["q"] for q in absent_questions(lib)]
    assert "my favourite pizza topping" in texts
    # make a transcript mention pizza: that topic must now be dropped
    from vl.db import Transcript
    tr = lib.query(Transcript).first()
    tr.text += " we ordered pizza"
    lib.commit()
    assert "my favourite pizza topping" not in [q["q"] for q in absent_questions(lib)]
    assert all(q["kind"] == "none" and q["expect"] == [] for q in absent_questions(lib))


def test_review_keep_drop_edit():
    qs = [
        {"q": "keep me", "kind": "content", "expect": ["a"], "check": "A | a"},
        {"q": "drop me", "kind": "content", "expect": ["b"], "check": "B | b"},
        {"q": "rewrite me", "kind": "content", "expect": ["c"], "check": "C | c"},
        {"q": "longest", "kind": "property", "expect": ["a"]},
    ]
    answers = iter(["", "n", "a better question"])
    out = review(qs, ask_user=lambda _: next(answers), show=lambda _: None)
    assert [q["q"] for q in out] == ["keep me", "a better question", "longest"]
    assert all(q.get("reviewed") for q in out if q["kind"] == "content")


def test_generated_file_loads_in_eval_and_names_exist(lib, tmp_path):
    content, _ = content_questions(lib, FakeWriter(), per_note=1)
    props, _ = property_questions(lib)
    qs = content + props + absent_questions(lib)
    p = tmp_path / "gen.json"
    p.write_text(json.dumps({"questions": qs}))
    loaded = load_questions(p)  # extra fields ("check", "reviewed") must not break the loader
    check_expected_exist(lib, loaded)
    assert len(loaded) == len(qs)


class _Msg:
    def __init__(self, text):
        self.content = [type("B", (), {"type": "text", "text": text})()]


class _Client:
    def __init__(self, text):
        self.messages, self.text = self, text

    def create(self, **kw):
        return _Msg(self.text)


def test_claude_writer_parses_and_rejects():
    ok = ClaudeQuestionWriter(client=_Client('Here: ["q one", " ", "q two", "q three"]'))
    assert ok.write("t", "s", "x", 2) == ["q one", "q two"]
    with pytest.raises(ValueError, match="no JSON array"):
        ClaudeQuestionWriter(client=_Client("sorry, no")).write("t", "s", "x", 2)
