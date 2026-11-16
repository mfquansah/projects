"""Audio-event tagging: find baby crying/laughing/babbling inside a recording. Runs locally; audio never leaves the Mac.

The pipeline depends on the SoundTagger protocol, so tests use a fake.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from vl.sounds.labels import BABY_CRY, BABY_LAUGH, canonical_label, reachable

WINDOW_S = 10  # the model analyses 10-second windows
DEFAULT_THRESHOLD = 0.10  # lowest confidence STORED. Searches decide what counts (see vl/ask.py), so tuning needs no re-run


@dataclass
class SoundHit:
    label: str
    start_s: float
    end_s: float
    confidence: float


class SoundTagger(Protocol):
    model_version: str

    def tag(self, audio_path: Path) -> list[SoundHit]: ...


def merge_hits(hits: list[SoundHit]) -> list[SoundHit]:
    """Merge touching/overlapping windows of the same label into one event, keeping the highest confidence."""
    out: list[SoundHit] = []
    for h in sorted(hits, key=lambda x: (x.label, x.start_s)):
        last = out[-1] if out else None
        if last and last.label == h.label and h.start_s <= last.end_s + 1e-6:
            last.end_s = max(last.end_s, h.end_s)
            last.confidence = max(last.confidence, h.confidence)
        else:
            out.append(SoundHit(h.label, h.start_s, h.end_s, h.confidence))
    return sorted(out, key=lambda x: x.start_s)


class AudioSetTagger:
    """AST model trained on AudioSet (527 sound classes). Needs `transformers` and `torch`.

    The first run downloads the model (several hundred MB). Speed on CPU is slow for long notes; pass device="mps"
    on Apple Silicon if it works for you.
    """

    def __init__(self, threshold: float = DEFAULT_THRESHOLD, device=None,
                 model: str = "MIT/ast-finetuned-audioset-10-10-0.4593", pipe=None) -> None:
        self.model_version = f"ast-audioset@{threshold}"
        self.threshold = threshold
        if pipe is not None:  # injected (tests): skip loading and checks
            self._pipe = pipe
            return
        from transformers import pipeline  # lazy: heavy
        from transformers.utils import is_speech_available

        if not is_speech_available():
            print("WARNING: the 'torchaudio' package is missing, so the model is receiving approximate audio features "
                  "(this is what the 'mel filter has all zero values' message means). Detection will be less accurate. "
                  "Fix: pip install --upgrade torch torchaudio", flush=True)
        self._pipe = pipeline("audio-classification", model=model, device=device)
        labels = list(self._pipe.model.config.id2label.values())
        found = reachable(labels)
        missing = {BABY_CRY, BABY_LAUGH} - found
        if missing:
            raise RuntimeError(
                f"The model has no labels that map to {sorted(missing)}, so those sounds could never be detected. "
                f"Labels containing 'cry'/'laugh': {[l for l in labels if 'cry' in l.lower() or 'laugh' in l.lower()]}")

    def inspect(self, audio_path: Path, windows: int = 3, top: int = 8) -> list[tuple[float, list[tuple[str, float]]]]:
        """What the model hears, with NO cutoff and NO label mapping: the top labels for the first few windows."""
        from faster_whisper.audio import decode_audio

        sr = 16000
        audio = decode_audio(str(audio_path), sampling_rate=sr)
        win = WINDOW_S * sr
        out = []
        for n, i in enumerate(range(0, len(audio), win)):
            chunk = audio[i:i + win]
            if n >= windows or len(chunk) < sr:
                break
            res = self._pipe({"raw": chunk, "sampling_rate": sr}, top_k=top, function_to_apply="sigmoid")
            out.append((i / sr, [(r["label"], float(r["score"])) for r in res]))
        return out

    def tag(self, audio_path: Path) -> list[SoundHit]:
        from faster_whisper.audio import decode_audio  # already installed; decodes any audio to 16 kHz mono

        sr = 16000
        audio = decode_audio(str(audio_path), sampling_rate=sr)
        win = WINDOW_S * sr
        hits: list[SoundHit] = []
        for i in range(0, len(audio), win):
            chunk = audio[i:i + win]
            if len(chunk) < sr:  # skip a sub-second tail
                break
            results = self._pipe({"raw": chunk, "sampling_rate": sr}, top_k=20, function_to_apply="sigmoid")
            for r in results:
                canon = canonical_label(r["label"])
                if canon and r["score"] >= self.threshold:
                    hits.append(SoundHit(canon, i / sr, min(i + win, len(audio)) / sr, float(r["score"])))
        return merge_hits(hits)
