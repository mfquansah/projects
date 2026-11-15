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

from vl.db import Category, Embedding, Enrichment, Note
from vl.index.embeddings import Embedder, cosine_scores, from_blob

RRF_K = 60


@dataclass
class Hit:
    note_id: int
    title: str
    summary: str
    category: str | None
    recorded_at: dt.datetime | None
    path: str
    score: float


def fts_query(q: str) -> str | None:
    """Turn free text into a safe FTS5 query: quoted tokens joined with OR."""
    tokens = re.findall(r"\w+", q.lower())
    return " OR ".join(f'"{t}"' for t in tokens) if tokens else None


def _candidate_ids(
    s: Session, category: str | None, since: dt.datetime | None, until: dt.datetime | None,
) -> set[int] | None:
    """None means 'no filter'. Otherwise the set of note ids allowed."""
    if category is None and since is None and until is None:
        return None
    query = s.query(Note.id).join(Enrichment, Enrichment.note_id == Note.id)
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
) -> list[Hit]:
    allowed = _candidate_ids(s, category, since, until)
    if allowed is not None and not allowed:
        return []

    scores: dict[int, float] = {}

    match = fts_query(q)
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
            order = np.argsort(-sims)[:50]
            for rank, idx in enumerate(order, start=1):
                nid = embs[idx].note_id
                scores[nid] = scores.get(nid, 0.0) + 1.0 / (RRF_K + rank)

    hits: list[Hit] = []
    for nid, score in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]:
        note = s.get(Note, nid)
        en = s.get(Enrichment, nid)
        cat = s.get(Category, en.category_id) if en and en.category_id else None
        hits.append(Hit(
            note_id=nid, title=en.title if en else note.original_name, summary=en.summary if en else "",
            category=cat.name if cat else None, recorded_at=note.recorded_at, path=note.path, score=score,
        ))
    return hits
