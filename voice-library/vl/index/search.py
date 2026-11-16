"""Hybrid search: keyword (FTS5) + meaning (embeddings), merged with reciprocal rank fusion.

Filters (category, date range) narrow the candidates first. LLM natural-language query parsing
and reranking is a separate, later layer (vl/enrich/query.py) that produces these same filters.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

import json

from vl.db import Category, Embedding, Enrichment, Note, NoteFlag, Transcript
from vl.index.embeddings import Embedder, cosine_scores, from_blob

RRF_K = 60
# Meaning search always has a 'nearest' note; without a cutoff, nonsense queries return unrelated notes.
# 0.25 is a starting guess for all-MiniLM-L6-v2 on normalized vectors: tune it during the pilot.
MIN_SIMILARITY = 0.25


@dataclass
class Hit:
    note_id: int
    title: str
    summary: str
    category: str | None
    recorded_at: dt.datetime | None
    path: str
    score: float
    why: str | None = None  # filled in by the LLM rerank step
    strength: str | None = None  # 'match' | 'partial' | 'related' from the rerank step; None = not judged
    duration_s: float | None = None  # see effective_duration
    sound_info: str | None = None  # e.g. 'baby_laugh 0.72 at 1:20', set when a sound filter matched
    sound_start_s: float | None = None  # where that sound starts, so a player can jump there
    sound_conf: float | None = None  # detector confidence 0-1 for that sound


def fts_query(q: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted tokens joined with OR."""
    tokens = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{t}"' for t in tokens) if tokens else None


def _candidate_ids(
    s: Session, category: str | None, since: dt.datetime | None, until: dt.datetime | None,
) -> set[int] | None:
    """None means 'no filter'. Otherwise the set of note ids allowed. Archived notes are always excluded."""
    archived = {r[0] for r in s.query(NoteFlag.note_id).filter_by(flag="archived")}
    if category is None and since is None and until is None and not archived:
        return None
    query = s.query(Note.id).join(Enrichment, Enrichment.note_id == Note.id)
    if archived:
        query = query.filter(~Note.id.in_(archived))
    if category is not None:
        query = query.join(Category, Category.id == Enrichment.category_id).filter(Category.name == category)
    if since is not None:
        query = query.filter(Note.recorded_at >= since)
    if until is not None:
        query = query.filter(Note.recorded_at < until)
    return {row[0] for row in query}


def search(
    s: Session, q: str, embedder: Embedder | None = None, *, limit: int = 10,
    category: str | None = None, since: dt.datetime | None = None, until: dt.datetime | None = None,
    keyword_q: str | None = None, min_similarity: float = MIN_SIMILARITY, only_ids: set[int] | None = None,
) -> list[Hit]:
    """`q` drives meaning search; `keyword_q` (default: q) drives keyword search."""
    allowed = _candidate_ids(s, category, since, until)
    if only_ids is not None:
        allowed = set(only_ids) if allowed is None else allowed & only_ids
    if allowed is not None and not allowed:
        return []

    scores: dict[int, float] = {}

    match = fts_query(q if keyword_q is None else keyword_q)
    if match:
        rows = s.execute(
            text("SELECT note_id FROM notes_fts WHERE notes_fts MATCH :m ORDER BY rank LIMIT 100"),
            {"m": match},
        ).all()
        rank = 0
        for (nid,) in rows:
            if allowed is not None and nid not in allowed:
                continue
            rank += 1
            scores[nid] = scores.get(nid, 0.0) + 1.0 / (RRF_K + rank)

    if embedder is not None:
        embs = s.query(Embedding).filter_by(model_version=embedder.model_version).all()
        if allowed is not None:
            embs = [e for e in embs if e.note_id in allowed]
        if embs:
            matrix = np.stack([from_blob(e.vector) for e in embs])
            sims = cosine_scores(embedder.embed([q])[0], matrix)
            order = [i for i in np.argsort(-sims)[:50] if sims[i] >= min_similarity]
            for rank, idx in enumerate(order, start=1):
                nid = embs[idx].note_id
                scores[nid] = scores.get(nid, 0.0) + 1.0 / (RRF_K + rank)

    return [make_hit(s, nid, score) for nid, score in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def effective_duration(s: Session, note: Note) -> float | None:
    """Stored duration, else the end of the last transcribed segment (approximate: ignores trailing silence)."""
    if note.duration_s:
        return note.duration_s
    tr = s.get(Transcript, note.id)
    if tr:
        try:
            segs = json.loads(tr.segments_json)
            ends = [float(x["end"]) for x in segs if "end" in x]
            return max(ends) if ends else None
        except (ValueError, TypeError, KeyError):
            return None
    return None


def make_hit(s: Session, nid: int, score: float = 0.0) -> Hit:
    note = s.get(Note, nid)
    en = s.get(Enrichment, nid)
    cat = s.get(Category, en.category_id) if en and en.category_id else None
    return Hit(
        note_id=nid, title=en.title if en else note.original_name, summary=en.summary if en else "",
        category=cat.name if cat else None, recorded_at=note.recorded_at, path=note.path, score=score,
        duration_s=effective_duration(s, note),
    )
