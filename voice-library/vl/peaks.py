"""Waveform shape for the player: loudness per slice of a recording, 0..1. Computed once and cached on disk."""
from __future__ import annotations

import json
from pathlib import Path


def compute_peaks(audio_path: Path, n: int = 96) -> list[float]:
    import numpy as np
    from faster_whisper.audio import decode_audio  # already a dependency; decodes anything to 16 kHz mono

    audio = np.abs(decode_audio(str(audio_path), sampling_rate=16000))
    if audio.size == 0:
        return [0.0] * n
    edges = np.linspace(0, audio.size, n + 1, dtype=int)
    raw = np.array([audio[a:b].max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])], dtype=float)
    top = raw.max()
    if top <= 0:
        return [0.0] * n
    return [round(float(v), 3) for v in np.sqrt(raw / top)]  # sqrt: quiet parts stay visible


def peaks_for(audio_path: Path, key: str, cache_dir: Path | None, n: int = 96) -> list[float]:
    cache = (cache_dir / f"{key[:32]}-{n}.json") if cache_dir else None
    if cache and cache.is_file():
        try:
            data = json.loads(cache.read_text())
            if isinstance(data, list) and len(data) == n:
                return data
        except (ValueError, OSError):
            pass
    peaks = compute_peaks(audio_path, n)
    if cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(peaks))
        except OSError:
            pass  # a cache that can't be written is fine
    return peaks
