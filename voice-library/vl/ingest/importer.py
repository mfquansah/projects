"""Import audio files from a folder into the library.

Idempotent: files are keyed by sha256, so re-importing the same folder adds nothing.
The recorded date is the best available: file birth time, else modified time, else a date in the filename.
Whether dates survive Voice Memos drag-out export is NOT verified yet; date_source records which one was used.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from vl.db import Note

AUDIO_EXTS = {".m4a", ".mp3", ".wav", ".aac", ".caf", ".qta"}

# e.g. "20241103 101530", "2024-11-03 10.15.30", "2024-11-03"
_NAME_DATE = re.compile(r"(20\d{2})[-_ ]?(\d{2})[-_ ]?(\d{2})(?:[-_ T]+(\d{2})[.:_-]?(\d{2})[.:_-]?(\d{2})?)?")


@dataclass
class ImportResult:
    added: int = 0
    skipped: int = 0
    failed: int = 0


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def date_from_filename(name: str) -> dt.datetime | None:
    m = _NAME_DATE.search(name)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    try:
        return dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0), int(ss or 0))
    except ValueError:
        return None


def best_date(path: Path) -> tuple[dt.datetime | None, str]:
    st = path.stat()
    birth = getattr(st, "st_birthtime", None)  # macOS exposes this; Linux usually does not
    if birth:
        return dt.datetime.fromtimestamp(birth), "birthtime"
    from_name = date_from_filename(path.name)
    if from_name:
        return from_name, "filename"
    return dt.datetime.fromtimestamp(st.st_mtime), "mtime"


def probe_duration(path: Path) -> float | None:
    """Duration in seconds if the optional 'mutagen' package is installed."""
    try:
        from mutagen import File  # type: ignore
    except ImportError:
        return None
    try:
        audio = File(path)
        return float(audio.info.length) if audio and audio.info else None
    except Exception:  # noqa: BLE001 - unreadable audio shouldn't stop the import
        return None


def import_folder(session: Session, folder: Path, store_dir: Path, limit: int | None = None) -> ImportResult:
    store_dir.mkdir(parents=True, exist_ok=True)
    result = ImportResult()
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS)
    for path in files:
        if limit is not None and result.added >= limit:
            break
        try:
            digest = sha256_of(path)
            if session.query(Note.id).filter_by(sha256=digest).first():
                result.skipped += 1
                continue
            recorded_at, source = best_date(path)
            dest = store_dir / f"{digest[:16]}{path.suffix.lower()}"
            if not dest.exists():
                shutil.copy2(path, dest)
            session.add(Note(
                sha256=digest, path=str(dest), original_name=path.name,
                recorded_at=recorded_at, date_source=source, duration_s=probe_duration(path),
            ))
            session.commit()
            result.added += 1
        except OSError:
            session.rollback()
            result.failed += 1
    return result
