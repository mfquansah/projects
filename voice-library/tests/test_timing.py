from pathlib import Path

from vl.timing import format_profile, profile_files
from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


class SlowTagger:
    model_version = "fake-ast"

    def tag(self, path):
        return []


def _files(tmp_path):
    out = []
    for n, body in (("a.m4a", "baby laughing"), ("b.m4a", "app idea")):
        p = tmp_path / n
        p.write_bytes(body.encode())
        out.append(p)
    return out


def test_profile_times_every_stage_and_leaves_no_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("VL_HOME", str(tmp_path / "home"))
    rows = profile_files(_files(tmp_path), FakeTranscriber(), FakeEnricher(), FakeEmbedder(), SlowTagger(), log=lambda *_: None)
    assert [r["name"] for r in rows] == ["a.m4a", "b.m4a"]
    for r in rows:
        assert set(r["stages"]) == {"transcribe", "enrich", "index", "sounds"} and not r["error"]
        assert r["total_s"] >= sum(r["stages"].values()) - 1e-6
    assert not (tmp_path / "home").exists()          # the real library folder was never created


def test_profile_without_sound_model_skips_that_stage(tmp_path):
    rows = profile_files(_files(tmp_path)[:1], FakeTranscriber(), FakeEnricher(), FakeEmbedder(), None, log=lambda *_: None)
    assert "sounds" not in rows[0]["stages"]


def test_format_names_slowest_stage_and_percentages():
    rows = [{"name": "x.m4a", "audio_s": 120.0, "error": "", "total_s": 100.0,
             "stages": {"transcribe": 60.0, "enrich": 5.0, "index": 5.0, "sounds": 30.0}}]
    txt = format_profile(rows, {"Whisper (small)": 7.0})
    assert "Slowest stage: Transcription (60% of the time)" in txt
    assert "30.0 s per audio minute" in txt and "50.0 s of work per minute of audio" in txt
    assert "Whisper (small)" in txt


def test_format_with_only_failures_does_not_divide_by_zero():
    rows = [{"name": "x.m4a", "audio_s": None, "error": "boom", "total_s": 1.0, "stages": {}}]
    assert "nothing to total" in format_profile(rows)
