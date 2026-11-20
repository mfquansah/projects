"""Timing tool: run a few recordings through every stage and report seconds per stage.

Works on a throwaway library in a temp folder, so your real library is never touched. Models are loaded first and
timed separately (loading is a one-off cost, not a per-recording cost).
"""
from __future__ import annotations

import tempfile
import time
from pathlib import Path

from vl.db import make_session_factory
from vl.ingest.importer import import_one
from vl.pipeline import ProcessResult, process_note
from vl.sounds.store import analyze_note

STAGES = ["transcribe", "enrich", "index", "sounds"]
LABELS = {"transcribe": "Transcription", "enrich": "Claude title/summary", "index": "Embedding + index",
          "sounds": "Sound detection"}


def audio_seconds(path: Path) -> float | None:
    try:
        import mutagen

        f = mutagen.File(str(path))
        return float(f.info.length) if f and f.info and f.info.length else None
    except Exception:  # noqa: BLE001 - duration is nice to have; the timing still works without it
        return None


def profile_files(paths: list[Path], transcriber, enricher, embedder, tagger, log=print) -> list[dict]:
    """Time each stage per file. `tagger` may be None (sounds skipped). Returns one dict per file."""
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="vl-timing-") as tmp:
        tmp_dir = Path(tmp)
        factory = make_session_factory(tmp_dir / "timing.db")
        for i, path in enumerate(paths, 1):
            row = {"name": path.name, "audio_s": audio_seconds(path), "stages": {}, "error": ""}
            log(f"[{i}/{len(paths)}] {path.name}")
            with factory() as s:
                note, _ = import_one(s, path, tmp_dir / "audio", original_name=path.name)
                if row["audio_s"] is None:
                    row["audio_s"] = note.duration_s
                cur = [None, 0.0]

                def lap(next_name: str | None) -> None:
                    now = time.perf_counter()
                    if cur[0]:
                        row["stages"][cur[0]] = row["stages"].get(cur[0], 0.0) + now - cur[1]
                    cur[:] = [next_name, now]

                t0 = time.perf_counter()
                result = ProcessResult()
                process_note(s, note, transcriber, enricher, embedder, result, on_stage=lap)
                lap(None)
                if result.errors:
                    row["error"] = "processing failed (see the stage that errored)"
                elif tagger is not None:
                    lap("sounds")
                    try:
                        analyze_note(s, tagger, note)
                    except Exception as exc:  # noqa: BLE001
                        row["error"] = f"sounds: {type(exc).__name__}: {exc}"
                    lap(None)
                row["total_s"] = time.perf_counter() - t0
            rows.append(row)
    return rows


def format_profile(rows: list[dict], loads: dict[str, float] | None = None) -> str:
    """Plain-text report: per-file table, per-audio-minute rates, and the slowest stage."""
    out: list[str] = []
    if loads:
        out.append("One-off model loading (not per recording):")
        out += [f"  {k:<22}{v:6.1f} s" for k, v in loads.items()]
        out.append("")
    ok = [r for r in rows if not r["error"]]
    head = f"{'Recording':<28}{'Audio':>8}" + "".join(f"{LABELS[s].split()[0]:>14}" for s in STAGES) + f"{'Total':>9}"
    out += ["Seconds per recording:", head, "-" * len(head)]
    for r in rows:
        audio = f"{r['audio_s'] / 60:.1f} min" if r["audio_s"] else "?"
        cells = "".join(f"{r['stages'].get(s, 0.0):>14.1f}" if s in r["stages"] else f"{'-':>14}" for s in STAGES)
        out.append(f"{r['name'][:27]:<28}{audio:>8}{cells}{r.get('total_s', 0.0):>9.1f}" + (f"  ERROR {r['error']}" if r["error"] else ""))
    totals = {s: sum(r["stages"].get(s, 0.0) for r in ok) for s in STAGES}
    grand = sum(totals.values())
    audio_total = sum(r["audio_s"] or 0 for r in ok)
    out.append("")
    if not ok or grand <= 0:
        out.append("No recording finished, so there is nothing to total.")
        return "\n".join(out)
    out.append("Where the time goes:")
    for s in sorted(STAGES, key=lambda k: -totals[k]):
        if totals[s] <= 0:
            continue
        per_min = f", {totals[s] / (audio_total / 60):.1f} s per audio minute" if audio_total else ""
        out.append(f"  {LABELS[s]:<24}{totals[s]:7.1f} s  {100 * totals[s] / grand:4.0f}%{per_min}")
    biggest = max(STAGES, key=lambda k: totals[k])
    out.append("")
    out.append(f"Slowest stage: {LABELS[biggest]} ({100 * totals[biggest] / grand:.0f}% of the time).")
    if audio_total:
        out.append(f"Overall: {grand / (audio_total / 60):.1f} s of work per minute of audio.")
    out.append("Note: the first recording can be a little slower (models warming up). Run 3 or more and compare.")
    return "\n".join(out)
