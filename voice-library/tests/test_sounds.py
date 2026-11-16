import datetime as dt

import pytest

from vl.ask import ask
from vl.db import Note, SoundEvent, Status
from vl.enrich.query import StructuredQuery
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes
from vl.sounds.labels import canonical_label, group_for, reachable
from vl.sounds.store import run_sounds, sound_scores, sounds_coverage
from vl.sounds.tagger import SoundHit, merge_hits

IDEA = "20241103 101530.m4a"   # older note
BABY = "20260801 090000.m4a"   # newer note
TODAY = dt.date(2026, 11, 15)


@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    return session, m


class FakeTagger:
    model_version = "fake-ast"

    def __init__(self, by_name=None, boom_on=None):
        self.by_name, self.boom_on, self.calls = by_name or {}, boom_on, []

    def tag(self, path):
        self.calls.append(path)
        if self.boom_on and self.boom_on in path.read_bytes().decode():
            raise RuntimeError("corrupt audio")
        text = path.read_bytes().decode()
        return list(self.by_name.get("baby" if "baby" in text else "idea", []))


def names(s, res):
    return [s.get(Note, h.note_id).original_name for h in res.hits]


class P:
    def __init__(self, **kw):
        self.sq = StructuredQuery(**{"semantic_text": "", **kw})

    def parse(self, q, c, t):
        return self.sq


# --- labels ---

@pytest.mark.parametrize("label, expected", [
    ("Baby cry, infant cry", "baby_cry"), ("Baby laughter", "baby_laugh"), ("Giggle", "giggle"),
    ("Laughter", "laughter"), ("Crying, sobbing", "crying"), ("Whimper", "whimper"),
    ("Babbling", "baby_babble"), ("Child speech, kid speaking", "child_speech"),
    ("Dog", None), ("Speech", None), ("Music", None)])
def test_canonical_label(label, expected):
    assert canonical_label(label) == expected


@pytest.mark.parametrize("sound, has", [
    ("baby_laughing", "baby_laugh"), ("giggling", "giggle"), ("baby_cry", "baby_cry"), ("crying", "crying"),
    ("cooing", "baby_babble"), ("babbling", "baby_babble")])
def test_group_for_understands_phrasings(sound, has):
    assert has in group_for(sound)


def test_group_for_unknown_sound_is_none():
    assert group_for("dog_barking") is None


def test_reachable_reports_missing_labels():
    assert {"baby_cry", "baby_laugh"} <= reachable(["Baby cry, infant cry", "Baby laughter", "Dog"])
    assert "baby_laugh" not in reachable(["Baby cry, infant cry", "Dog"])


# --- merging ---

def test_merge_joins_touching_windows_and_keeps_best_confidence():
    out = merge_hits([SoundHit("baby_cry", 0, 10, 0.4), SoundHit("baby_cry", 10, 20, 0.9),
                      SoundHit("baby_cry", 40, 50, 0.5), SoundHit("giggle", 0, 10, 0.6)])
    cry = [h for h in out if h.label == "baby_cry"]
    assert [(h.start_s, h.end_s, h.confidence) for h in cry] == [(0, 20, 0.9), (40, 50, 0.5)]
    assert len(out) == 3


# --- running over notes ---

LAUGH = SoundHit("baby_laugh", 70.0, 80.0, 0.82)


def test_run_sounds_is_idempotent_and_resumable(lib):
    s, _ = lib
    tagger = FakeTagger({"baby": [LAUGH]})
    r1 = run_sounds(s, tagger)
    assert (r1["analyzed"], r1["events"], r1["errors"]) == (2, 1, 0)
    assert sounds_coverage(s) == (2, 2)
    r2 = run_sounds(s, tagger)
    assert r2["analyzed"] == 0 and len(tagger.calls) == 2  # nothing re-analyzed


def test_run_sounds_limit_and_failure_isolation(lib):
    s, _ = lib
    assert run_sounds(s, FakeTagger(), limit=1)["analyzed"] == 1
    s.query(Status).filter_by(stage="sounds").delete()
    s.query(SoundEvent).delete()
    s.commit()
    r = run_sounds(s, FakeTagger({"baby": [LAUGH]}, boom_on="baby"))
    assert r["errors"] == 1 and r["analyzed"] == 1
    err = s.query(Status).filter_by(stage="sounds", state="error").one()
    assert "corrupt audio" in err.error
    # fixing the problem and re-running retries only the failed note
    assert run_sounds(s, FakeTagger({"baby": [LAUGH]}))["analyzed"] == 1


def test_sound_scores_respects_labels_and_confidence(lib):
    s, _ = lib
    run_sounds(s, FakeTagger({"baby": [LAUGH, SoundHit("baby_cry", 5, 15, 0.31)]}))
    got = sound_scores(s, ("baby_laugh", "giggle"), 0.3)
    assert len(got) == 1 and list(got.values())[0][1:] == ("baby_laugh", 70.0)
    assert sound_scores(s, ("baby_laugh",), 0.9) == {}


# --- ask with a sound filter ---

def test_ask_finds_note_by_sound_even_when_transcript_never_mentions_it(lib):
    s, m = lib
    run_sounds(s, FakeTagger({"baby": [LAUGH]}))
    # the question's topic words appear in NO transcript; only the sound can find it
    res = ask(s, "q", P(sound="baby_laugh", semantic_text="zzzz", keywords=["zzzz"]), m, today=TODAY)
    assert names(s, res) == [BABY]
    assert res.hits[0].sound_info == "baby_laugh 0.82 at 1:10"


def test_sound_confidence_ranks_results_and_filters_apply(lib):
    s, m = lib
    run_sounds(s, FakeTagger({"baby": [SoundHit("giggle", 0, 10, 0.5)], "idea": [SoundHit("baby_laugh", 0, 10, 0.9)]}))
    assert names(s, ask(s, "q", P(sound="laugh"), m, today=TODAY)) == [IDEA, BABY]  # 0.9 before 0.5
    res = ask(s, "q", P(sound="laugh", since=dt.datetime(2026, 1, 1), until=dt.datetime(2027, 1, 1)), m, today=TODAY)
    assert names(s, res) == [BABY]


def test_no_matching_sound_is_honest_not_a_guess(lib):
    s, m = lib
    run_sounds(s, FakeTagger())  # analyzed, nothing found
    res = ask(s, "q", P(sound="baby_cry", semantic_text="baby", keywords=["baby"]), m, today=TODAY)
    assert res.hits == [] and any("No notes contain" in n for n in res.notes)


def test_sound_ignored_with_a_clear_note_when_not_analyzed_or_unknown(lib):
    s, m = lib
    res = ask(s, "q", P(sound="baby_laugh", semantic_text="baby laughing", keywords=["baby"]), m, today=TODAY)
    assert any("hasn't been run" in n for n in res.notes) and res.hits  # falls back to normal search
    run_sounds(s, FakeTagger())
    res = ask(s, "q", P(sound="dog_barking", semantic_text="baby", keywords=["baby"]), m, today=TODAY)
    assert any("don't know how to detect" in n for n in res.notes) and res.hits


def test_partial_coverage_is_reported(lib):
    s, m = lib
    run_sounds(s, FakeTagger({"idea": [LAUGH]}), limit=1)
    res = ask(s, "q", P(sound="baby_laugh"), m, today=TODAY)
    assert any("Only 1 of 2 notes" in n for n in res.notes)


def test_sound_plus_sort_and_no_rerank(lib):
    s, m = lib
    for n in s.query(Note):
        n.duration_s = 30.0 if n.original_name == IDEA else 90.0
    s.commit()
    run_sounds(s, FakeTagger({"baby": [LAUGH], "idea": [LAUGH]}))

    class Boom:
        def rerank(self, *a):
            raise AssertionError("must not rerank sound results")

    res = ask(s, "q", P(sound="laugh", sort="longest", count=1), m, Boom(), today=TODAY)
    assert names(s, res) == [BABY]
    res = ask(s, "q", P(sound="laugh"), m, Boom(), today=TODAY)
    assert len(res.hits) == 2
