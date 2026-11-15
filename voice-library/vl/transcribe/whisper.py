"""Transcription. The pipeline depends only on the Transcriber protocol so tests use a fake."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class TranscriptResult:
    text: str
    segments: list[dict] = field(default_factory=list)  # [{start, end, text}]
    model_version: str = ""


class Transcriber(Protocol):
    model_version: str

    def transcribe(self, audio_path: Path) -> TranscriptResult: ...


class FasterWhisperTranscriber:
    """Local transcription with faster-whisper. Install: pip install faster-whisper"""

    def __init__(self, model_size: str = "small") -> None:
        from faster_whisper import WhisperModel  # lazy: heavy dependency

        self.model_version = f"faster-whisper-{model_size}"
        self._model = WhisperModel(model_size, compute_type="int8")

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        segments, _info = self._model.transcribe(str(audio_path), vad_filter=True)
        segs = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
        return TranscriptResult(
            text=" ".join(s["text"] for s in segs).strip(),
            segments=segs,
            model_version=self.model_version,
        )
