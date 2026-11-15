import json
from pathlib import Path

import numpy as np
import pytest

from vl.db import make_session_factory
from vl.enrich.llm import EnrichmentResult
from vl.transcribe.whisper import TranscriptResult


@pytest.fixture
def session(tmp_path):
    factory = make_session_factory(tmp_path / "test.db")
    with factory() as s:
        yield s


@pytest.fixture
def audio_folder(tmp_path) -> Path:
    folder = tmp_path / "exports"
    folder.mkdir()
    # Fake "audio": content is what the fake transcriber reads back as the transcript.
    (folder / "20241103 101530.m4a").write_bytes(b"my idea for a better app name called Echo")
    (folder / "20260801 090000.m4a").write_bytes(b"baby laughing at the dog this morning so cute")
    (folder / "notes.txt").write_text("not audio")
    return folder


class FakeTranscriber:
    model_version = "fake-whisper"

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        text = audio_path.read_bytes().decode()
        return TranscriptResult(text=text, segments=[{"start": 0, "end": 1, "text": text}],
                                model_version=self.model_version)


class FakeEnricher:
    model_version = "fake-llm"

    def enrich(self, transcript, categories, recorded_at):
        cat = "Family memories" if "baby" in transcript else "Ideas"
        return EnrichmentResult(title=transcript[:20].title(), summary=f"About: {transcript}",
                                category=cat, tags=["baby"] if "baby" in transcript else ["app"],
                                model_version=self.model_version)


class FakeEmbedder:
    """Bag-of-keywords embedding so 'child' lands near 'baby' without a real model."""
    model_version = "fake-embed"
    GROUPS = [("baby", "child", "kid"), ("laugh", "laughing", "giggle"), ("idea", "name", "app")]

    def embed(self, texts):
        out = np.zeros((len(texts), len(self.GROUPS)), dtype=np.float32)
        for i, t in enumerate(texts):
            for j, group in enumerate(self.GROUPS):
                out[i, j] = sum(w in t.lower() for w in group)
        return out


@pytest.fixture
def fakes():
    return FakeTranscriber(), FakeEnricher(), FakeEmbedder()
