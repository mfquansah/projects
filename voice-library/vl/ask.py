"""Ask the library a question in plain language.

question -> LLM parses into filters -> hybrid search -> (optional) LLM rerank with a one-line "why".
Designed to degrade gracefully: if the LLM fails, it falls back to plain search on the raw question and says so.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from vl.db import Note, Transcript
from vl.enrich.query import QueryParser, Reranker, StructuredQuery
from vl.index.embeddings import Embedder
from vl.index.search import Hit, _candidate_ids, make_hit, search
from vl.pipeline import accepted_category_names
from vl.sounds.labels import group_for, infer_sound
from vl.sounds.store import sound_scores, sounds_coverage

RERANK_TOP = 10
MIN_SOUND_CONFIDENCE = 0.3  # untuned: tune on real recordings
TOPIC_BONUS = 0.2  # a transcript match nudges a sound match up; sound confidence stays the main signal


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

    if not sq.sound:  # the parser missed it (or failed): a baby word plus a sound word is enough
        guess = infer_sound(question)
        if guess:
            sq.sound = guess
    sound_map = None
    if sq.sound:
        group = group_for(sq.sound)
        analyzed, total = sounds_coverage(s)
        if group is None:
            notes.append(f"I don't know how to detect '{sq.sound}', so that part of the question was ignored.")
        elif analyzed == 0:
            notes.append("Sound detection hasn't been run on your notes yet (run: python -m vl.cli sounds), "
                         "so the sound part of the question was ignored.")
        else:
            sound_map = sound_scores(s, group, MIN_SOUND_CONFIDENCE)
            if analyzed < total:
                notes.append(f"Only {analyzed} of {total} notes have been checked for sounds so far.")

    def run() -> list[Hit]:
        if sound_map is not None:
            ids = set(sound_map)
            allowed = _candidate_ids(s, category, since, until)
            if allowed is not None:
                ids &= allowed
            if not ids:
                return []
            topical: set[int] = set()
            if sq.semantic_text.strip():
                topical = {h.note_id for h in search(s, sq.semantic_text, embedder, limit=50, only_ids=ids,
                                                     keyword_q=keyword_q)}
            ranked = sorted(ids, key=lambda i: -(sound_map[i][0] + (TOPIC_BONUS if i in topical else 0)))
            out = []
            for i in ranked:
                h = make_hit(s, i, score=sound_map[i][0])
                conf, label, start = sound_map[i]
                h.sound_info = f"{label} {conf:.2f} at {int(start // 60)}:{int(start % 60):02d}"
                out.append(h)
            return out
        if sq.sort and not sq.semantic_text.strip():
            # pure property question ("my longest note"): every note that passes the filters is a candidate
            ids = _candidate_ids(s, category, since, until)
            if ids is None:
                ids = {row[0] for row in s.query(Note.id)}
            return [make_hit(s, i) for i in sorted(ids)]
        return search(s, sq.semantic_text, embedder, limit=50 if sq.sort else limit, category=category,
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

    if sound_map is not None and not hits:
        notes.append(f"No notes contain '{sq.sound}' sounds above the confidence cutoff ({MIN_SOUND_CONFIDENCE}).")

    if sq.sort:  # deterministic order: never rerank, Claude would scramble it
        return AskResult(hits=_sort_hits(hits, sq.sort, notes)[: sq.count or limit], query=sq, notes=notes)

    if reranker and len(hits) > 1 and sound_map is None:  # sound results are ordered by confidence; keep that
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
    if not out:  # Claude endorsed nothing: don't throw everything away, keep the search order
        notes.append("Claude didn't judge any result a close match, so these are in plain search order.")
        return hits
    dropped = len(by_id) + len(tail)
    if dropped:
        notes.append(f"Claude set aside {dropped} weaker result(s) that didn't match the question.")
    return out


def _sort_hits(hits: list[Hit], sort: str, notes: list[str]) -> list[Hit]:
    by_length = sort in ("longest", "shortest")
    key = (lambda h: h.duration_s) if by_length else (lambda h: h.recorded_at)
    known = [h for h in hits if key(h) is not None]
    if len(known) < len(hits):
        what = "length" if by_length else "recording date"
        notes.append(f"{len(hits) - len(known)} note(s) have no {what} on record, so they were left out of the ordering.")
    if not known and hits:
        notes.append(f"No {sort} ordering is possible because none of the matching notes has that information.")
        return hits
    if by_length:
        notes.append("Lengths may be approximate for notes where only transcript timing was available (trailing silence isn't counted).")
    return sorted(known, key=key, reverse=sort in ("longest", "newest"))
