"""Import audio files from a folder into the library.

Idempotent: files are keyed by sha256, so re-importing the same folder adds nothing.
The recorded date is the best available: a date in the filename, else the date stored inside the audio, else file times.
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


_MP4_EPOCH = dt.datetime(1904, 1, 1, tzinfo=dt.timezone.utc)


def _atoms(data: bytes, start: int, end: int):
    """Yield (type, payload_start, payload_end) for MP4 atoms in data[start:end]."""
    pos = start
    while pos + 8 <= end:
        size = int.from_bytes(data[pos:pos + 4], "big")
        kind = data[pos + 4:pos + 8]
        header = 8
        if size == 1 and pos + 16 <= end:  # 64-bit size
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
            header = 16
        elif size == 0:  # atom runs to the end of the enclosing range
            size = end - pos
        if size < header or pos + size > end:
            return
        yield kind, pos + header, pos + size
        pos += size


def metadata_date(path: Path) -> dt.datetime | None:
    """Recording time stored INSIDE an .m4a (the MP4 'mvhd' creation time, UTC), as local naive time.

    A drag-out export is a byte copy, so this survives even when file times are the export time.
    Returns None if absent or implausible (0 or outside 2007..tomorrow). Only the 'moov' atom is read.
    """
    try:
        with path.open("rb") as f:
            head = f.read(1 << 20)  # moov is normally within the first MB; otherwise we just return None
    except OSError:
        return None
    for kind, ps, pe in _atoms(head, 0, len(head)):
        if kind != b"moov":
            continue
        for k2, s2, e2 in _atoms(head, ps, pe):
            if k2 != b"mvhd" or e2 - s2 < 12:
                continue
            version = head[s2]
            width = 8 if version == 1 else 4
            raw = int.from_bytes(head[s2 + 4:s2 + 4 + width], "big")
            if raw == 0:
                return None
            try:
                when = _MP4_EPOCH + dt.timedelta(seconds=raw)
            except OverflowError:
                return None
            now = dt.datetime.now(dt.timezone.utc)
            if not (dt.datetime(2007, 1, 1, tzinfo=dt.timezone.utc) <= when <= now + dt.timedelta(days=1)):
                return None
            return when.astimezone().replace(tzinfo=None)
    return None


def best_date(path: Path, name: str | None = None) -> tuple[dt.datetime | None, str]:
    """Most trustworthy first: date in the filename, then date stored inside the audio, then file times.

    A file dragged out of Voice Memos is a COPY, so birth/modified time is often the EXPORT time.
    `date_source` records which was used: filename | metadata | birthtime | mtime.
    """
    from_name = date_from_filename(name or path.name)
    if from_name:
        return from_name, "filename"
    inside = metadata_date(path)
    if inside:
        return inside, "metadata"
    st = path.stat()
    birth = getattr(st, "st_birthtime", None)  # macOS exposes this; Linux usually does not
    if birth:
        return dt.datetime.fromtimestamp(birth), "birthtime"
    return dt.datetime.fromtimestamp(st.st_mtime), "mtime"


def redate_notes(session: Session) -> tuple[int, int]:
    """Re-derive dates for already-imported notes from the filename and the audio's own metadata only.

    Never replaces a date with a file-time guess. Returns (changed, unchanged).
    """
    changed = unchanged = 0
    for note in session.query(Note).all():
        date, source = best_date(Path(note.path), note.original_name)
        if source in ("filename", "metadata") and (date != note.recorded_at or source != note.date_source):
            note.recorded_at, note.date_source = date, source
            changed += 1
        else:
            unchanged += 1
    session.commit()
    return changed, unchanged


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
