"""Run sound tagging over notes and query the results. Idempotent and resumable, like the other stages."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from vl.db import Note, SoundEvent, Status
from vl.sounds.tagger import SoundTagger

STAGE = "sounds"


def run_sounds(s: Session, tagger: SoundTagger, limit: int | None = None,
               progress: Callable[[str], None] | None = None) -> dict[str, int]:
    done = {r[0] for r in s.query(Status.note_id).filter_by(stage=STAGE, state="done")}
    counts = {"analyzed": 0, "events": 0, "errors": 0}
    for note in s.query(Note).order_by(Note.id).all():
        if note.id in done:
            continue
        if limit is not None and counts["analyzed"] + counts["errors"] >= limit:
            break
        try:
            hits = tagger.tag(Path(note.path))
            s.query(SoundEvent).filter_by(note_id=note.id).delete()
            for h in hits:
                s.add(SoundEvent(note_id=note.id, label=h.label, start_s=h.start_s, end_s=h.end_s,
                                 confidence=h.confidence, model_version=tagger.model_version))
            s.merge(Status(note_id=note.id, stage=STAGE, state="done", error=None))
            s.commit()
            counts["analyzed"] += 1
            counts["events"] += len(hits)
            if progress:
                progress(f"{note.original_name}: {len(hits)} event(s)")
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the batch
            s.rollback()
            s.merge(Status(note_id=note.id, stage=STAGE, state="error", error=f"{type(exc).__name__}: {exc}"))
            s.commit()
            counts["errors"] += 1
    return counts


def sounds_coverage(s: Session) -> tuple[int, int]:
    """(notes analyzed for sounds, total notes)."""
    analyzed = s.query(func.count(Status.note_id)).filter_by(stage=STAGE, state="done").scalar() or 0
    return analyzed, s.query(func.count(Note.id)).scalar() or 0


def sound_scores(s: Session, labels: tuple[str, ...], min_conf: float) -> dict[int, tuple[float, str, float]]:
    """note_id -> (best confidence, label, start seconds) over events whose label is in `labels`."""
    best: dict[int, tuple[float, str, float]] = {}
    for ev in s.query(SoundEvent).filter(SoundEvent.label.in_(labels), SoundEvent.confidence >= min_conf):
        if ev.note_id not in best or ev.confidence > best[ev.note_id][0]:
            best[ev.note_id] = (ev.confidence, ev.label, ev.start_s)
    return best
