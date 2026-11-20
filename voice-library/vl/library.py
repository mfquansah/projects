"""Browsing and curation: categories, suggested categories, tags, review queue, note details.

'Archive' only hides a note; the audio file and its data stay. `delete_note` is the one permanent removal: it erases the
library's own copy and data (never the user's original in Voice Memos) and remembers the fingerprint so it is not re-imported.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from vl.db import (
    Category, DeletedNote, Embedding, Enrichment, Note, NoteEdit, NoteFlag, SoundEvent, Status, Transcript,
)
from vl.index.embeddings import cosine_scores, from_blob
from vl.index.search import Hit, effective_duration, make_hit


def _archived(s: Session) -> set[int]:
    return {r[0] for r in s.query(NoteFlag.note_id).filter_by(flag="archived")}


def _norm(name: str) -> str:
    return " ".join(name.split())


def category_counts(s: Session) -> list[dict]:
    """Accepted categories with how many (non-archived) notes each holds, plus 'Uncategorized' if any."""
    archived = _archived(s)
    counts: dict[int | None, int] = {}
    for cid, nid in s.query(Enrichment.category_id, Enrichment.note_id):
        if nid not in archived:
            counts[cid] = counts.get(cid, 0) + 1
    out = [{"id": c.id, "name": c.name, "origin": c.origin, "count": counts.get(c.id, 0)}
           for c in s.query(Category).filter_by(accepted=True).order_by(Category.id)]
    if counts.get(None):
        out.append({"id": None, "name": "Uncategorized", "origin": "none", "count": counts[None]})
    return out


def suggested_categories(s: Session) -> list[dict]:
    """New categories Claude proposed that you haven't accepted or rejected yet, most-requested first."""
    known = {c.name.lower() for c in s.query(Category)}  # accepted and rejected names are both 'decided'
    archived = _archived(s)
    found: dict[str, list[int]] = {}   # keyed by lowercase so 'Songs' and 'songs' are one suggestion
    shown: dict[str, str] = {}         # the spelling to display (first one seen)
    for nid, name in s.query(Enrichment.note_id, Enrichment.suggested_category).filter(
            Enrichment.suggested_category.isnot(None)):
        name = _norm(name or "")
        key = name.lower()
        if name and key not in known and nid not in archived:
            found.setdefault(key, []).append(nid)
            shown.setdefault(key, name)
    return sorted(({"name": shown[k], "count": len(ids), "note_ids": ids} for k, ids in found.items()),
                  key=lambda d: (-d["count"], d["name"]))


def _notes_with_suggestion(s: Session, name: str):
    return [e for e in s.query(Enrichment).filter(Enrichment.suggested_category.isnot(None))
            if _norm(e.suggested_category or "").lower() == name.lower()]


def accept_suggestion(s: Session, name: str) -> dict:
    """Create the category and move every note that suggested it into it."""
    name = _norm(name)
    notes = _notes_with_suggestion(s, name)
    if not notes:
        raise ValueError(f"No notes are suggesting a category called {name!r}.")
    cat = s.query(Category).filter(func.lower(Category.name) == name.lower()).first()
    if cat is None:
        cat = Category(name=name, origin="suggested", accepted=True)
        s.add(cat)
        s.flush()
    else:
        cat.accepted = True
    for e in notes:
        e.category_id = cat.id
        e.suggested_category = None
    s.commit()
    return {"category": cat.name, "id": cat.id, "moved": len(notes)}


def reject_suggestion(s: Session, name: str) -> int:
    """Remember the rejection (so it isn't suggested again) and clear it from the notes."""
    name = _norm(name)
    notes = _notes_with_suggestion(s, name)
    if not s.query(Category).filter(func.lower(Category.name) == name.lower()).first():
        s.add(Category(name=name, origin="suggested", accepted=False))
    for e in notes:
        e.suggested_category = None
    s.commit()
    return len(notes)


def tag_counts(s: Session, limit: int = 50) -> list[dict]:
    """Most common free-form tags (non-archived notes), for 'turn a tag into a category'."""
    archived = _archived(s)
    counts: dict[str, int] = {}
    for nid, tags in s.query(Enrichment.note_id, Enrichment.tags_json):
        if nid in archived:
            continue
        for t in json.loads(tags or "[]"):
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": c} for t, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def create_category(s: Session, name: str, from_tag: str | None = None) -> dict:
    """Create a category by hand. With `from_tag`, every note carrying that tag moves into it."""
    name = _norm(name)
    if not name or len(name) > 80:
        raise ValueError("A category name must be 1-80 characters.")
    existing = s.query(Category).filter(func.lower(Category.name) == name.lower()).first()
    if existing and existing.accepted:
        raise ValueError(f"A category called {existing.name!r} already exists.")
    if existing:  # previously rejected suggestion: the user now wants it
        existing.accepted, existing.origin, cat = True, "user", existing
    else:
        cat = Category(name=name, origin="user", accepted=True)
        s.add(cat)
        s.flush()
    moved = 0
    if from_tag:
        archived = _archived(s)
        for e in s.query(Enrichment):
            if e.note_id not in archived and from_tag in json.loads(e.tags_json or "[]"):
                e.category_id = cat.id
                moved += 1
    s.commit()
    return {"category": cat.name, "id": cat.id, "moved": moved}


def assign_category(s: Session, note_id: int, category_id: int | None) -> None:
    en = s.get(Enrichment, note_id)
    if en is None:
        raise ValueError("That note hasn't been labelled yet.")
    if category_id is not None and not s.query(Category).filter_by(id=category_id, accepted=True).first():
        raise ValueError("That category doesn't exist.")
    en.category_id = category_id
    _mark_edited(s, note_id, "category")
    s.commit()


FLAGS = ("archived", "keep")


def set_flag(s: Session, note_id: int, flag: str) -> None:
    if flag not in FLAGS:
        raise ValueError(f"Unknown flag {flag!r}.")
    if s.get(Note, note_id) is None:
        raise ValueError("No such note.")
    s.merge(NoteFlag(note_id=note_id, flag=flag))
    s.commit()


def clear_flag(s: Session, note_id: int) -> None:
    s.query(NoteFlag).filter_by(note_id=note_id).delete()
    s.commit()


def delete_note(s: Session, note_id: int, audio_root: Path | None = None, cache_dir: Path | None = None) -> dict:
    """Permanently remove a recording from the library: its data, the library's copy of the audio and its waveform cache.

    The user's original (e.g. in Voice Memos) is never touched. The recording's fingerprint is remembered so that a later
    import or sync skips it. The audio copy is only removed if it sits inside `audio_root`.
    Raises ValueError if there is no such note.
    """
    note = s.get(Note, note_id)
    if note is None:
        raise ValueError("No such note.")
    sha, name, path = note.sha256, note.original_name, Path(note.path)
    for model in (Transcript, Enrichment, Embedding, SoundEvent, Status, NoteFlag, NoteEdit):
        s.query(model).filter_by(note_id=note_id).delete()
    s.execute(text("DELETE FROM notes_fts WHERE note_id = :id"), {"id": note_id})
    s.delete(note)
    s.merge(DeletedNote(sha256=sha, original_name=name or ""))
    s.commit()
    audio_removed = False
    try:
        if audio_root is not None and Path(audio_root).resolve() in path.resolve().parents and path.is_file():
            path.unlink()
            audio_removed = True
    except OSError:
        pass   # the data is gone; a leftover file can be removed by hand
    if cache_dir is not None:
        for f in Path(cache_dir).glob(f"{sha[:32]}-*.json"):
            try:
                f.unlink()
            except OSError:
                pass
    return {"deleted": True, "audio_removed": audio_removed}


def review_queue(s: Session, min_junk: float = 0.5, limit: int = 50) -> list[dict]:
    """Notes Claude thinks may be accidental or empty, most likely first. Skips ones you already kept or archived."""
    flagged = {r[0] for r in s.query(NoteFlag.note_id)}
    rows = (s.query(Note, Enrichment).join(Enrichment, Enrichment.note_id == Note.id)
            .filter(Enrichment.junk_score >= min_junk).order_by(Enrichment.junk_score.desc(), Note.id).all())
    return [{"id": n.id, "title": e.title, "summary": e.summary, "junk_score": e.junk_score,
             "recorded_at": n.recorded_at.isoformat() if n.recorded_at else None,
             "duration_s": effective_duration(s, n)}
            for n, e in rows if n.id not in flagged][:limit]


def archived_notes(s: Session) -> list[dict]:
    rows = (s.query(Note, Enrichment).outerjoin(Enrichment, Enrichment.note_id == Note.id)
            .join(NoteFlag, NoteFlag.note_id == Note.id).filter(NoteFlag.flag == "archived").order_by(Note.id).all())
    return [{"id": n.id, "title": e.title if e else n.original_name,
             "recorded_at": n.recorded_at.isoformat() if n.recorded_at else None} for n, e in rows]


def note_detail(s: Session, note_id: int) -> dict | None:
    note = s.get(Note, note_id)
    if note is None:
        return None
    en, tr = s.get(Enrichment, note_id), s.get(Transcript, note_id)
    cat = s.get(Category, en.category_id) if en and en.category_id else None
    flag = s.get(NoteFlag, note_id)
    events = [{"label": e.label, "start_s": e.start_s, "end_s": e.end_s, "confidence": round(e.confidence, 2)}
              for e in s.query(SoundEvent).filter_by(note_id=note_id).order_by(SoundEvent.start_s)]
    return {
        "id": note.id, "file": note.original_name,
        "recorded_at": note.recorded_at.isoformat() if note.recorded_at else None,
        "date_source": note.date_source, "duration_s": effective_duration(s, note),
        "title": en.title if en else note.original_name, "summary": en.summary if en else "",
        "category": cat.name if cat else None, "category_id": cat.id if cat else None,
        "suggested_category": en.suggested_category if en else None,
        "purpose": en.purpose if en else "", "tags": json.loads(en.tags_json) if en else [],
        "junk_score": en.junk_score if en else None,
        "transcript": tr.text if tr else "", "segments": _segments(tr), "sounds": events,
        "flag": flag.flag if flag else None, "imported_at": note.imported_at.isoformat() if note.imported_at else None,
        "edited": _edited(s, note_id),
    }


SORTS = ("newest", "oldest", "longest", "shortest", "title")


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def browse_notes(s: Session, category_id: int | None = None, uncategorized: bool = False, sort: str = "newest",
                 since: str | None = None, until: str | None = None, min_s: float | None = None, max_s: float | None = None,
                 tag: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[Hit], int]:
    """A page of notes plus how many match in all, for the All recordings page and collection lists.

    Filters: collection, recorded date range (inclusive, 'YYYY-MM-DD'), length range in seconds (notes whose length isn't
    known are left out of a length filter), and one tag. Sorting puts notes with an unknown length last. Archived notes
    are never listed. Raises ValueError for an unknown sort or a bad date.
    """
    if sort not in SORTS:
        raise ValueError(f"Unknown sort {sort!r}.")
    try:
        d_from = dt.datetime.combine(dt.date.fromisoformat(since), dt.time.min) if since else None
        d_to = dt.datetime.combine(dt.date.fromisoformat(until), dt.time.min) + dt.timedelta(days=1) if until else None
    except ValueError as exc:
        raise ValueError("Dates must look like 2026-11-20.") from exc
    archived = _archived(s)
    q = s.query(Note.id).join(Enrichment, Enrichment.note_id == Note.id)
    if uncategorized:
        q = q.filter(Enrichment.category_id.is_(None))
    elif category_id is not None:
        q = q.filter(Enrichment.category_id == category_id)
    if archived:
        q = q.filter(~Note.id.in_(archived))
    if d_from is not None:
        q = q.filter(Note.recorded_at >= d_from)
    if d_to is not None:
        q = q.filter(Note.recorded_at < d_to)
    if min_s is not None:
        q = q.filter(Note.duration_s >= min_s)
    if max_s is not None:
        q = q.filter(Note.duration_s <= max_s)
    if tag:
        q = q.filter(Enrichment.tags_json.like(f'%"{_like_escape(tag.strip().lower())}"%', escape="\\"))
    total = q.count()
    newest = (Note.recorded_at.is_(None), Note.recorded_at.desc(), Note.id.desc())
    order = {
        "newest": newest,
        "oldest": (Note.recorded_at.is_(None), Note.recorded_at.asc(), Note.id.asc()),
        "longest": (Note.duration_s.is_(None), Note.duration_s.desc(), *newest),
        "shortest": (Note.duration_s.is_(None), Note.duration_s.asc(), *newest),
        "title": (func.lower(Enrichment.title).asc(), Note.id.asc()),
    }[sort]
    ids = [r[0] for r in q.order_by(*order).offset(max(offset, 0)).limit(min(max(limit, 1), 100))]
    return [make_hit(s, i) for i in ids], total


def bulk_action(s: Session, action: str, ids: list[int], audio_root: Path | None = None, cache_dir: Path | None = None) -> dict:
    """Archive or permanently delete several notes. One that can't be processed is reported, and the rest still go through."""
    if action not in ("archive", "delete"):
        raise ValueError("Action must be 'archive' or 'delete'.")
    done, failed = 0, []
    for nid in dict.fromkeys(ids):
        try:
            if action == "archive":
                set_flag(s, nid, "archived")
            else:
                delete_note(s, nid, audio_root, cache_dir)
            done += 1
        except ValueError as exc:
            s.rollback()
            failed.append({"id": nid, "error": str(exc)})
    return {"done": done, "failed": failed}


def list_notes(s: Session, category_id: int | None = None, uncategorized: bool = False,
               limit: int = 30, offset: int = 0) -> list[Hit]:
    """Browse: newest first, optionally one category (or the uncategorized ones). Archived notes are never listed."""
    archived = _archived(s)
    q = s.query(Note.id).join(Enrichment, Enrichment.note_id == Note.id)
    if uncategorized:
        q = q.filter(Enrichment.category_id.is_(None))
    elif category_id is not None:
        q = q.filter(Enrichment.category_id == category_id)
    if archived:
        q = q.filter(~Note.id.in_(archived))
    q = q.order_by(Note.recorded_at.is_(None), Note.recorded_at.desc(), Note.id.desc())
    ids = [r[0] for r in q.offset(max(offset, 0)).limit(min(max(limit, 1), 100))]
    return [make_hit(s, i) for i in ids]


def _segments(tr: Transcript | None) -> list[dict]:
    if tr is None:
        return []
    try:
        return [{"start": float(x["start"]), "end": float(x.get("end", x["start"])), "text": str(x.get("text", "")).strip()}
                for x in json.loads(tr.segments_json) if str(x.get("text", "")).strip()]
    except (ValueError, TypeError, KeyError):
        return []


def _edited(s: Session, note_id: int) -> list[str]:
    row = s.get(NoteEdit, note_id)
    return json.loads(row.fields) if row else []


def _mark_edited(s: Session, note_id: int, field: str) -> None:
    fields = _edited(s, note_id)
    if field not in fields:
        s.merge(NoteEdit(note_id=note_id, fields=json.dumps(fields + [field])))


def update_details(s: Session, note_id: int, title: str | None = None, summary: str | None = None,
                   tags: list[str] | None = None, embedder=None) -> dict:
    """Edit a note's title, summary or tags by hand. The search index is refreshed so the change is searchable."""
    en = s.get(Enrichment, note_id)
    note = s.get(Note, note_id)
    if en is None or note is None:
        raise ValueError("That note hasn't been labelled yet.")
    if title is not None:
        title = " ".join(title.split())
        if not 1 <= len(title) <= 200:
            raise ValueError("A title must be 1-200 characters.")
        if title != en.title:
            en.title = title
            _mark_edited(s, note_id, "title")
    if summary is not None:
        summary = summary.strip()
        if len(summary) > 2000:
            raise ValueError("A summary can be at most 2000 characters.")
        if summary != en.summary:
            en.summary = summary
            _mark_edited(s, note_id, "summary")
    if tags is not None:
        clean: list[str] = []
        for t in tags:
            t = " ".join(str(t).lower().split())
            if t and t not in clean:
                if len(t) > 40:
                    raise ValueError("A tag can be at most 40 characters.")
                clean.append(t)
        if len(clean) > 12:
            raise ValueError("A note can have at most 12 tags.")
        if clean != json.loads(en.tags_json or "[]"):
            en.tags_json = json.dumps(clean)
            _mark_edited(s, note_id, "tags")
    s.commit()
    from vl.pipeline import index_note  # local import: pipeline doesn't depend on this module
    index_note(s, note, embedder)
    return note_detail(s, note_id)


def related_notes(s: Session, note_id: int, model_version: str, limit: int = 3, min_similarity: float = 0.35) -> list[dict]:
    """Other notes whose meaning is close to this one (by embeddings), skipping archived ones."""
    import numpy as np

    rows = s.query(Embedding).filter_by(model_version=model_version).all()
    me = next((r for r in rows if r.note_id == note_id), None)
    if me is None:
        return []
    archived = _archived(s)
    others = [r for r in rows if r.note_id != note_id and r.note_id not in archived]
    if not others:
        return []
    sims = cosine_scores(from_blob(me.vector), np.stack([from_blob(r.vector) for r in others]))
    out = []
    for i in np.argsort(-sims)[:limit]:
        if sims[i] < min_similarity:
            break
        h = make_hit(s, others[i].note_id)
        out.append({"id": h.note_id, "title": h.title, "category": h.category,
                    "recorded_at": h.recorded_at.isoformat() if h.recorded_at else None})
    return out


def attention(s: Session) -> dict:
    """Everything waiting on a decision: suggested categories, likely-junk notes, and what's archived."""
    sug, rev = suggested_categories(s), review_queue(s)
    return {"suggestions": sug, "review": rev, "archived": archived_notes(s), "count": len(sug) + len(rev)}


def try_queries(s: Session, n: int = 3) -> list[str]:
    """Example searches drawn from the library itself: titles of recent notes from different categories."""
    archived = _archived(s)
    rows = (s.query(Note, Enrichment).join(Enrichment, Enrichment.note_id == Note.id)
            .order_by(Note.recorded_at.is_(None), Note.recorded_at.desc(), Note.id.desc()).limit(60).all())
    seen_cat: set = set()
    out: list[str] = []
    for note, en in rows:
        if note.id in archived or en.junk_score >= 0.5 or not en.title.strip():
            continue
        if en.category_id in seen_cat:
            continue
        seen_cat.add(en.category_id)
        out.append(en.title)
        if len(out) == n:
            break
    return out
