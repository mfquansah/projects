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


def test_filename_date_beats_file_times(tmp_path):
    from vl.ingest.importer import best_date
    f = tmp_path / "20241103 101530.m4a"
    f.write_bytes(b"x")  # file times are 'now'; the name says 2024
    assert best_date(f) == (dt.datetime(2024, 11, 3, 10, 15, 30), "filename")
    g = tmp_path / "New Recording 5.m4a"
    g.write_bytes(b"x")
    d, src = best_date(g)
    assert src in ("birthtime", "mtime") and d is not None


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
    # dates come from the filename (it outranks file times, which can be the export time)
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


# --- dates stored inside the audio (MP4 mvhd) ---

def _atom(kind: bytes, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + kind + payload


def _mp4_with_creation(when_utc: dt.datetime, version: int = 0) -> bytes:
    secs = int((when_utc - dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)).total_seconds())
    width = 8 if version == 1 else 4
    body = bytes([version]) + b"\0\0\0" + secs.to_bytes(width, "big") + b"\0" * 20
    return _atom(b"ftyp", b"M4A \0\0\0\0") + _atom(b"moov", _atom(b"mvhd", body))


def test_metadata_date_is_read_and_beats_file_times(tmp_path):
    from vl.ingest.importer import best_date, metadata_date
    utc = dt.datetime(2024, 11, 3, 15, 30, 0, tzinfo=dt.timezone.utc)
    for version in (0, 1):
        f = tmp_path / f"New Recording {version}.m4a"
        f.write_bytes(_mp4_with_creation(utc, version))
        expected = utc.astimezone().replace(tzinfo=None)
        assert metadata_date(f) == expected
        assert best_date(f) == (expected, "metadata")


def test_metadata_date_rejects_garbage(tmp_path):
    from vl.ingest.importer import metadata_date
    zero = tmp_path / "zero.m4a"
    zero.write_bytes(_mp4_with_creation(dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)))
    future = tmp_path / "future.m4a"
    future.write_bytes(_mp4_with_creation(dt.datetime(2035, 1, 1, tzinfo=dt.timezone.utc)))
    junk = tmp_path / "junk.m4a"
    junk.write_bytes(b"not an mp4 at all" * 10)
    empty = tmp_path / "empty.m4a"
    empty.write_bytes(b"")
    assert metadata_date(zero) is None and metadata_date(future) is None
    assert metadata_date(junk) is None and metadata_date(empty) is None
    assert metadata_date(tmp_path / "missing.m4a") is None


def test_redate_fixes_export_time_dates_without_guessing(session, tmp_path):
    from vl.ingest.importer import import_folder, redate_notes
    folder = tmp_path / "exp"
    folder.mkdir()
    real = dt.datetime(2023, 5, 6, 12, 0, 0, tzinfo=dt.timezone.utc)
    (folder / "New Recording 1.m4a").write_bytes(_mp4_with_creation(real))
    (folder / "New Recording 2.m4a").write_bytes(b"plain bytes, no metadata")
    # simulate the old importer: both notes carry export-time dates
    import_folder(session, folder, tmp_path / "audio")
    for n in session.query(Note).all():
        n.recorded_at, n.date_source = dt.datetime(2026, 11, 15, 6, 40), "birthtime"
    session.commit()
    changed, unchanged = redate_notes(session)
    assert (changed, unchanged) == (1, 1)
    by_name = {n.original_name: n for n in session.query(Note)}
    assert by_name["New Recording 1.m4a"].date_source == "metadata"
    assert by_name["New Recording 1.m4a"].recorded_at == real.astimezone().replace(tzinfo=None)
    assert by_name["New Recording 2.m4a"].recorded_at == dt.datetime(2026, 11, 15, 6, 40)  # not guessed
    assert redate_notes(session) == (0, 2)  # idempotent
