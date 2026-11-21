import json
import struct
import wave

import pytest

from vl import library as lib_
from vl.db import Enrichment, Note, NoteEdit, Transcript
from vl.ingest.importer import import_folder
from vl.peaks import compute_peaks, peaks_for
from vl.pipeline import process_notes
from vl.snippets import best_snippet, query_terms

IDEA = "20241103 101530.m4a"
BABY = "20260801 090000.m4a"

SEGS = [
    {"start": 0.0, "end": 12.0, "text": "Okay, quick one before I forget. We keep running out of the same four things."},
    {"start": 14.0, "end": 30.0, "text": "What if the grocery list just learned? It notices you buy oats every ten days."},
    {"start": 38.0, "end": 50.0, "text": "It nudges you before you run out of the groceries."},
]


# ---------- snippets ----------

def test_query_terms_drop_filler_and_duplicates():
    assert query_terms("that idea about a grocery list", "grocery", "lists") == ["grocery", "list", "lists"]
    assert query_terms("the a of") == []


def test_best_snippet_picks_the_segment_with_most_distinct_terms_and_marks_matches():
    sn = best_snippet(SEGS, "", query_terms("grocery list oats"))
    assert sn["t"] == 14.0
    marked = [p["t"] for p in sn["parts"] if p["m"]]
    assert marked == ["grocery", "list", "oats"]
    assert "".join(p["t"] for p in sn["parts"]).startswith("What if the grocery list just learned?")


def test_snippet_matches_word_beginnings_so_plurals_are_highlighted():
    sn = best_snippet(SEGS, "", ["grocer"])
    assert any(p["m"] and p["t"].lower() == "grocery" for p in best_snippet(SEGS, "", ["grocery"])["parts"])
    assert sn is not None


def test_no_match_or_no_terms_means_no_snippet():
    assert best_snippet(SEGS, "", ["zebra"]) is None
    assert best_snippet(SEGS, "", []) is None


def test_long_segments_are_windowed_around_the_match_with_ellipses():
    long = {"start": 5.0, "end": 60.0, "text": ("filler " * 40) + "the grocery list is the point " + ("more " * 40)}
    sn = best_snippet([long], "", ["grocery"], max_chars=120)
    text = "".join(p["t"] for p in sn["parts"])
    assert text.startswith("…") and text.endswith("…") and len(text) < 140 and "grocery" in text


def test_falls_back_to_full_text_without_timestamps():
    sn = best_snippet([], "we talked about the grocery list today", ["grocery"])
    assert sn["t"] is None and any(p["m"] for p in sn["parts"])


# ---------- peaks ----------

def _wav(path, seconds=2, loud_second=1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        frames = b""
        for s in range(seconds):
            amp = 20000 if s == loud_second else 500
            frames += b"".join(struct.pack("<h", amp if i % 40 < 20 else -amp) for i in range(16000))
        w.writeframes(frames)
    return path


def test_peaks_have_n_values_in_range_and_show_the_loud_part(tmp_path):
    p = compute_peaks(_wav(tmp_path / "a.wav"), n=20)
    assert len(p) == 20 and all(0 <= v <= 1 for v in p)
    assert max(p[10:]) == 1.0 and max(p[:10]) < 0.5  # second half is the loud second


def test_peaks_are_cached_and_a_bad_cache_is_recomputed(tmp_path):
    wav = _wav(tmp_path / "a.wav")
    cache = tmp_path / "cache"
    first = peaks_for(wav, "abc", cache, n=16)
    assert (cache / "abc-16.json").is_file()
    wav.unlink()  # proves the second call reads the cache, not the audio
    assert peaks_for(wav, "abc", cache, n=16) == first
    (cache / "abc-16.json").write_text("not json")
    with pytest.raises(Exception):
        peaks_for(wav, "abc", cache, n=16)  # corrupt cache + missing audio: a real error, not a silent wrong answer


def test_silent_audio_gives_flat_peaks(tmp_path):
    p = tmp_path / "s.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    assert compute_peaks(p, n=8) == [0.0] * 8


# ---------- library: details, related, attention ----------

@pytest.fixture
def lib(session, audio_folder, tmp_path, fakes):
    t, e, m = fakes
    import_folder(session, audio_folder, tmp_path / "audio")
    process_notes(session, t, e, m)
    return session, m


def nid(s, name):
    return s.query(Note).filter_by(original_name=name).one().id


def test_update_details_edits_validates_and_stays_searchable(lib):
    s, m = lib
    from vl.index.search import search
    n = nid(s, IDEA)
    d = lib_.update_details(s, n, title="  Better   name   Echo ", tags=["App", " naming ", "app"], embedder=m)
    assert d["title"] == "Better name Echo" and d["tags"] == ["app", "naming"]
    assert set(d["edited"]) == {"title", "tags"}
    assert [h.title for h in search(s, "Better name Echo", None)][:1] == ["Better name Echo"]  # re-indexed
    # no change -> not recorded as an edit; the category change is
    lib_.update_details(s, n, title="Better name Echo")
    assert set(lib_.note_detail(s, n)["edited"]) == {"title", "tags"}
    for bad in (dict(title=""), dict(title="x" * 201), dict(summary="y" * 2001),
                dict(tags=["t" * 41]), dict(tags=[f"t{i}" for i in range(13)])):
        with pytest.raises(ValueError):
            lib_.update_details(s, n, **bad)
    with pytest.raises(ValueError, match="hasn't been labelled"):
        lib_.update_details(s, 9999, title="x")


def test_changing_category_is_recorded_as_an_edit(lib):
    s, _ = lib
    n = nid(s, IDEA)
    from vl.db import Category
    fam = s.query(Category).filter_by(name="Family memories").one().id
    lib_.assign_category(s, n, fam)
    assert lib_.note_detail(s, n)["edited"] == ["category"]


def test_detail_includes_timestamped_segments(lib):
    s, _ = lib
    n = nid(s, BABY)
    s.get(Transcript, n).segments_json = json.dumps(SEGS + [{"start": 60, "end": 61, "text": "   "}, {"bad": 1}])
    s.commit()
    d = lib_.note_detail(s, n)
    assert [x["start"] for x in d["segments"]] == [0.0, 14.0, 38.0]  # blank and malformed segments dropped
    s.get(Transcript, n).segments_json = "garbage"
    s.commit()
    assert lib_.note_detail(s, n)["segments"] == []


def test_related_notes_use_meaning_and_skip_self_and_archived(lib):
    s, m = lib
    a, b = nid(s, IDEA), nid(s, BABY)
    assert lib_.related_notes(s, a, m.model_version, min_similarity=0.0) == [
        {"id": b, "title": s.get(Enrichment, b).title, "category": "Family memories",
         "recorded_at": s.get(Note, b).recorded_at.isoformat()}]
    assert lib_.related_notes(s, a, m.model_version, min_similarity=0.99) == []  # too dissimilar
    assert lib_.related_notes(s, a, "other-model") == []
    lib_.set_flag(s, b, "archived")
    assert lib_.related_notes(s, a, m.model_version, min_similarity=0.0) == []


def test_attention_and_try_queries(lib):
    s, _ = lib
    s.get(Enrichment, nid(s, IDEA)).suggested_category = "Naming"
    s.get(Enrichment, nid(s, BABY)).junk_score = 0.9
    s.commit()
    a = lib_.attention(s)
    assert a["count"] == 2 and [x["name"] for x in a["suggestions"]] == ["Naming"] and len(a["review"]) == 1
    tries = lib_.try_queries(s, 3)
    assert len(tries) == 1 and tries[0] == s.get(Enrichment, nid(s, IDEA)).title  # junk-scored note isn't suggested
