import datetime as dt

from vl.db import Enrichment, Note, Status, Transcript
from vl.enrich.llm import parse_enrichment
from vl.ingest.importer import date_from_filename, import_folder
from vl.index.search import fts_query, search
from vl.pipeline import process_notes

CATS = ["Ideas", "Family memories", "Work & projects", "Personal reflections", "Other"]


def test_import_is_idempotent(session, audio_folder, tmp_path):
    store = tmp_path / "audio"
    first = import_folder(session, audio_folder, store)
    assert (first.added, first.skipped) == (2, 0)  # notes.txt ignored
    second = import_folder(session, audio_folder, store)
    assert (second.added, second.skipped) == (0, 2)


def test_import_limit(session, audio_folder, tmp_path):
    assert import_folder(session, audio_folder, tmp_path / "audio", limit=1).added == 1


def test_filename_dates():
    assert date_from_filename("20241103 101530.m4a") == dt.datetime(2024, 11, 3, 10, 15, 30)
    assert date_from_filename("New Recording 12.m4a") is None
    assert date_from_filename("2024-13-45.m4a") is None  # invalid date


def test_process_is_resumable_and_idempotent(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    r1 = process_notes(session, t, e, m)
    assert (r1.transcribed, r1.enriched, r1.indexed, r1.errors) == (2, 2, 2, 0)
    r2 = process_notes(session, t, e, m)
    assert (r2.transcribed, r2.enriched, r2.indexed) == (0, 0, 0)


def test_one_failure_does_not_stop_batch(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")

    class FlakyTranscriber:
        model_version = "flaky"
        calls = 0

        def transcribe(self, path):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("corrupt audio")
            return t.transcribe(path)

    r = process_notes(session, FlakyTranscriber(), e, m)
    assert r.errors == 1 and r.indexed == 1
    err = session.query(Status).filter_by(state="error").one()
    assert "corrupt audio" in err.error
    # fixing the problem and re-running picks up only the failed note
    r2 = process_notes(session, t, e, m)
    assert r2.transcribed == 1 and r2.errors == 0


def test_keyword_and_meaning_search(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)

    kw = search(session, "Echo", None)
    assert [h.title for h in kw] and "app" in kw[0].summary.lower()

    # "child giggle" shares no words with the transcript; only meaning search finds it
    assert search(session, "child giggle", None) == []
    sem = search(session, "child giggle", m)
    assert sem and sem[0].category == "Family memories"


def test_filters(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    # Linux has no birthtime; dates come from the filename here
    only_2026 = search(session, "baby idea app", m, since=dt.datetime(2026, 1, 1))
    assert {h.category for h in only_2026} == {"Family memories"}
    ideas = search(session, "baby idea app", m, category="Ideas")
    assert {h.category for h in ideas} == {"Ideas"}
    assert search(session, "baby", m, category="Work & projects") == []


def test_fts_query_is_safe():
    assert fts_query('what "is" this? AND OR') == '"what" OR "is" OR "this" OR "and" OR "or"'
    assert fts_query("?!") is None


def test_parse_enrichment_tolerates_wrapping_and_bad_values():
    raw = 'Sure!\n```json\n{"title":"A","summary":"B","category":"Nonsense","suggested_category":"Songs","tags":["X"," "],"junk_score":5}\n```'
    r = parse_enrichment(raw, CATS, "m")
    assert r.category == "Other" and r.suggested_category == "Songs"
    assert r.tags == ["x"] and r.junk_score == 1.0


def test_suggested_category_is_never_applied(session, audio_folder, tmp_path, fakes):
    t, _, m = fakes
    from vl.enrich.llm import EnrichmentResult

    class SuggestingEnricher:
        model_version = "s"

        def enrich(self, transcript, categories, recorded_at):
            return EnrichmentResult(title="x", summary="y", category="Other", suggested_category="Songs")

    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, SuggestingEnricher(), m)
    en = session.query(Enrichment).first()
    assert en.suggested_category == "Songs"
    from vl.db import Category
    assert session.query(Category).filter_by(name="Songs").first() is None
