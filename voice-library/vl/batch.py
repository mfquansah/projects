"""Test-batch support: pick the newest recordings not yet imported, and turn per-file timings into an estimate for the rest."""
from __future__ import annotations

import statistics
from pathlib import Path

from sqlalchemy.orm import Session

from vl.db import Enrichment, Note
from vl.ingest.importer import probe_duration, sha256_of


def pick_new(files: list[Path], n: int, session: Session) -> list[Path]:
    """The first `n` files (in the order given, so pass newest first) that still need importing.

    A recording that was imported but never finished (e.g. you stopped the app part-way) counts as still needing work,
    so a restarted batch picks it up again instead of skipping it.
    """
    out: list[Path] = []
    for p in files:
        if len(out) >= n:
            break
        try:
            note = session.query(Note).filter_by(sha256=sha256_of(p)).first()
            if note is None or session.get(Enrichment, note.id) is None:
                out.append(p)
        except OSError:
            continue
    return out


def remaining_audio_seconds(rest: list[Path], fallback_mean_s: float | None) -> float | None:
    """Total audio length of the files not in the batch. Unreadable ones count as the batch's average length."""
    if not rest:
        return 0.0
    known = [d for d in (probe_duration(p) for p in rest) if d]
    if known:
        return sum(known) + (fallback_mean_s or statistics.mean(known)) * (len(rest) - len(known))
    return fallback_mean_s * len(rest) if fallback_mean_s else None


def build_report(files: list[dict], remaining_files: int, remaining_audio_s: float | None,
                 price_in: float | None = None, price_out: float | None = None) -> dict:
    """Summarise a finished batch. Only notes that were actually processed count (duplicates and failures are listed apart).

    Prices are USD per million tokens; without both, no dollar figures are produced (tokens only).
    """
    ok = [f for f in files if f["state"] == "done"]
    failed = [f for f in files if f["state"] == "error"]
    secs = [f["seconds"] for f in ok]
    audio_total = sum((f.get("audio_s") or 0) for f in ok)
    t_in = sum(f.get("tokens_in", 0) for f in ok)
    t_out = sum(f.get("tokens_out", 0) for f in ok)
    calls = sum(f.get("calls", 0) for f in ok)
    total = sum(secs)
    rate = total / (audio_total / 60) if audio_total > 0 else None   # seconds of work per minute of audio

    def cost(tin, tout):
        return None if price_in is None or price_out is None else (tin * price_in + tout * price_out) / 1e6

    rep = {
        "processed": len(ok), "failed": [{"name": f["name"], "error": f["error"]} for f in failed],
        "duplicates": sum(1 for f in files if f["state"] == "duplicate"),
        "seconds": {"total": total, "mean": statistics.mean(secs) if secs else None,
                    "median": statistics.median(secs) if secs else None, "max": max(secs) if secs else None},
        "audio_minutes": audio_total / 60, "seconds_per_audio_minute": rate,
        "tokens": {"input": t_in, "output": t_out, "calls": calls},
        "cost_usd": cost(t_in, t_out),
        "slowest": [{"name": f["name"], "seconds": f["seconds"], "audio_s": f.get("audio_s")}
                    for f in sorted(ok, key=lambda x: -x["seconds"])[:3]],
        "remaining": None,
    }
    if ok and remaining_files > 0:
        if rate and remaining_audio_s:
            est_s, basis, factor = rate * (remaining_audio_s / 60), "audio length", remaining_audio_s / audio_total
        else:
            est_s, basis, factor = statistics.mean(secs) * remaining_files, "per recording", remaining_files / len(ok)
        rep["remaining"] = {
            "files": remaining_files, "audio_minutes": (remaining_audio_s / 60) if remaining_audio_s else None,
            "est_seconds": est_s, "basis": basis, "est_tokens": {"input": int(t_in * factor), "output": int(t_out * factor)},
            "est_cost_usd": cost(t_in * factor, t_out * factor),
        }
    return rep
