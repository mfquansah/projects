"""Browsing and curation: categories, suggested categories, tags, review queue, note details.

Nothing here deletes a recording. 'Archive' only hides a note; the audio file and its data stay.
"""
from __future__ import annotations

import json

from sqlalchemy import func
from sqlalchemy.orm import Session

from vl.db import Category, Enrichment, Note, NoteFlag, SoundEvent, Transcript
from vl.index.search import effective_duration


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
        "transcript": tr.text if tr else "", "sounds": events, "flag": flag.flag if flag else None,
    }
