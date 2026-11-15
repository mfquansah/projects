"""Process imported notes: transcribe -> enrich -> index. Each stage is idempotent and resumable.

A note that already has a result for a stage is skipped, so re-running only does new work.
A failure on one note is recorded in `status` and never stops the rest of the batch.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from vl.db import Category, Embedding, Enrichment, Note, Status, Transcript
from vl.enrich.llm import Enricher
from vl.index.embeddings import Embedder, to_blob
from vl.transcribe.whisper import Transcriber


@dataclass
class ProcessResult:
    transcribed: int = 0
    enriched: int = 0
    indexed: int = 0
    errors: int = 0


def _set_status(s: Session, note_id: int, stage: str, state: str, error: str | None = None) -> None:
    s.merge(Status(note_id=note_id, stage=stage, state=state, error=error))
    s.commit()


def accepted_category_names(s: Session) -> list[str]:
    return [c.name for c in s.query(Category).filter_by(accepted=True).order_by(Category.id)]


def index_note(s: Session, note: Note, embedder: Embedder | None) -> None:
    tr = s.get(Transcript, note.id)
    en = s.get(Enrichment, note.id)
    if not tr or not en:
        return
    tags = " ".join(json.loads(en.tags_json))
    s.execute(text("DELETE FROM notes_fts WHERE note_id = :id"), {"id": note.id})
    s.execute(
        text("INSERT INTO notes_fts(title, summary, body, tags, note_id) VALUES (:t, :s, :b, :g, :id)"),
        {"t": en.title, "s": en.summary, "b": tr.text, "g": tags, "id": note.id},
    )
    if embedder is not None:
        doc = f"{en.title}. {en.summary} {tr.text[:2000]}"
        vec = embedder.embed([doc])[0]
        s.merge(Embedding(note_id=note.id, model_version=embedder.model_version,
                          dim=len(vec), vector=to_blob(vec)))
    s.commit()


def process_notes(
    s: Session, transcriber: Transcriber, enricher: Enricher, embedder: Embedder | None,
    limit: int | None = None,
) -> ProcessResult:
    result = ProcessResult()
    notes = s.query(Note).order_by(Note.id).all()
    done = 0
    for note in notes:
        needs_t = s.get(Transcript, note.id) is None
        needs_e = s.get(Enrichment, note.id) is None
        needs_i = embedder is not None and s.get(Embedding, note.id) is None
        fts_missing = s.execute(
            text("SELECT 1 FROM notes_fts WHERE note_id = :id"), {"id": note.id}).first() is None
        if not (needs_t or needs_e or needs_i or fts_missing):
            continue
        if limit is not None and done >= limit:
            break
        done += 1
        stage = "transcribe"
        try:
            if needs_t:
                tr = transcriber.transcribe(Path(note.path))
                s.add(Transcript(note_id=note.id, text=tr.text,
                                 segments_json=json.dumps(tr.segments), model_version=tr.model_version))
                s.commit()
                _set_status(s, note.id, "transcribe", "done")
                result.transcribed += 1
            stage = "enrich"
            if needs_e:
                transcript = s.get(Transcript, note.id).text
                names = accepted_category_names(s)
                er = enricher.enrich(transcript, names, note.recorded_at.isoformat() if note.recorded_at else None)
                cat = s.query(Category).filter_by(name=er.category).first()
                s.add(Enrichment(
                    note_id=note.id, title=er.title, summary=er.summary,
                    category_id=cat.id if cat else None, suggested_category=er.suggested_category,
                    purpose=er.purpose, tags_json=json.dumps(er.tags), junk_score=er.junk_score,
                    model_version=er.model_version))
                s.commit()
                _set_status(s, note.id, "enrich", "done")
                result.enriched += 1
            stage = "index"
            index_note(s, note, embedder)
            _set_status(s, note.id, "index", "done")
            result.indexed += 1
        except Exception as exc:  # noqa: BLE001 - one bad note must not stop the batch
            s.rollback()
            _set_status(s, note.id, stage, "error", f"{type(exc).__name__}: {exc}")
            result.errors += 1
    return result
