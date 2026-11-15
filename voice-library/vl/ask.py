"""Ask the library a question in plain language.

question -> LLM parses into filters -> hybrid search -> (optional) LLM rerank with a one-line "why".
Designed to degrade gracefully: if the LLM fails, it falls back to plain search on the raw question and says so.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from vl.db import Transcript
from vl.enrich.query import QueryParser, Reranker, StructuredQuery
from vl.index.embeddings import Embedder
from vl.index.search import Hit, search
from vl.pipeline import accepted_category_names

RERANK_TOP = 10


@dataclass
class AskResult:
    hits: list[Hit]
    query: StructuredQuery
    notes: list[str] = field(default_factory=list)  # honest messages: fallbacks, relaxed filters, ignored parts


def ask(
    s: Session, question: str, parser: QueryParser, embedder: Embedder | None,
    reranker: Reranker | None = None, *, today: dt.date | None = None, limit: int = 10,
) -> AskResult:
    today = today or dt.date.today()
    notes: list[str] = []

    try:
        sq = parser.parse(question, accepted_category_names(s), today)
    except Exception as exc:  # noqa: BLE001 - never lose the search because the LLM failed
        sq = StructuredQuery(semantic_text=question)
        notes.append(f"Couldn't interpret the question with the LLM ({type(exc).__name__}); used plain search.")
    notes.extend(sq.notes)

    keyword_q = " ".join(sq.keywords) or sq.semantic_text
    category, since, until = sq.category, sq.since, sq.until

    def run() -> list[Hit]:
        return search(s, sq.semantic_text, embedder, limit=limit, category=category,
                      since=since, until=until, keyword_q=keyword_q)

    hits = run()
    # Relax gently, and always say so. Category first; dates last because recorded dates may be unreliable.
    if not hits and category:
        category = None
        hits = run()
        if hits:
            notes.append(f"Nothing matched in category '{sq.category}', so I searched all categories.")
    if not hits and (since or until):
        since = until = None
        hits = run()
        if hits:
            notes.append("Nothing matched in that date range, so I searched all dates. "
                         "Recorded dates may be inaccurate; check them.")

    if reranker and len(hits) > 1:
        hits = _rerank(s, question, hits, reranker, notes)
    return AskResult(hits=hits, query=sq, notes=notes)


def _rerank(s: Session, question: str, hits: list[Hit], reranker: Reranker, notes: list[str]) -> list[Hit]:
    head, tail = hits[:RERANK_TOP], hits[RERANK_TOP:]
    cands = []
    for h in head:
        tr = s.get(Transcript, h.note_id)
        cands.append({"id": h.note_id, "title": h.title, "summary": h.summary,
                      "snippet": (tr.text[:300] if tr else "")})
    try:
        ranked = reranker.rerank(question, cands)
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Couldn't rerank with the LLM ({type(exc).__name__}); showing search order.")
        return hits
    by_id = {h.note_id: h for h in head}
    out: list[Hit] = []
    for r in ranked:
        h = by_id.pop(r["id"], None)
        if h:
            h.why = r["why"] or None
            out.append(h)
    out.extend(by_id.values())  # candidates the LLM omitted stay, after the matches it endorsed, with no "why"
    return out + tail
