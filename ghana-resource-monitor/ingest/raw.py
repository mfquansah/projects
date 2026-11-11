"""Raw document store: register a source file exactly as received, by content hash, never overwriting.

    data/raw/<source_id>/<YYYY-MM-DD>_<sha256 first 12>_<original filename>

The file is copied (read-only) and a `documents` row records its hash, path, page count and parse status. Registering
the same file for the same source again is a no-op. A changed file has a different hash, so it becomes a new document
beside the old one. Large raw files are git-ignored: the database keeps the hash and metadata, and production keeps the
files in S3-compatible object storage under the same key.

Usage: python -m ingest.raw SOURCE_ID FILE [--published YYYY-MM-DD] [--db PATH]
"""
import argparse
import hashlib
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Document, Source
from ingest.load import ROOT, migrate, resolve_url

CHUNK = 1 << 20


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(CHUNK):  # streamed: raw PDFs can be hundreds of MB
            h.update(block)
    return h.hexdigest()


def pdf_pages(path: Path):
    if path.suffix.lower() != ".pdf":
        return None
    try:
        out = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, timeout=60).stdout
        return next((int(line.split()[-1]) for line in out.splitlines() if line.startswith("Pages:")), None)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def register_document(session: Session, source_id: str, src: Path, raw_root: Path = ROOT / "data" / "raw",
                      published: date | None = None, today: date | None = None):
    """Store `src` in the raw store and record it. Returns (Document, created). Idempotent per (source, content)."""
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(src)
    if session.get(Source, source_id) is None:
        raise ValueError(f"unknown source {source_id!r}; add it to the source register first")
    digest = sha256_file(src)
    existing = session.scalars(select(Document).where(Document.source_id == source_id, Document.sha256 == digest)).first()
    if existing:
        return existing, False
    when = today or datetime.now(timezone.utc).date()
    dest = raw_root / source_id / f"{when:%Y-%m-%d}_{digest[:12]}_{src.name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if sha256_file(dest) != digest:  # the name embeds the hash, so this means corruption: never overwrite
            raise RuntimeError(f"{dest} exists with different content; refusing to overwrite")
    else:
        shutil.copy2(src, dest)
        dest.chmod(0o444)
    try:
        rel = str(dest.relative_to(ROOT))
    except ValueError:
        rel = str(dest)
    doc = Document(source_id=source_id, raw_path=rel, sha256=digest, published_date=published, pages=pdf_pages(dest),
                   parse_status="pending")
    session.add(doc)
    session.flush()
    return doc, True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source_id")
    ap.add_argument("file")
    ap.add_argument("--published", type=date.fromisoformat, default=None)
    ap.add_argument("--db", default=None)
    a = ap.parse_args(argv)
    url = resolve_url(a.db)
    migrate(url)
    engine = create_engine(url)
    try:
        with Session(engine) as s, s.begin():
            doc, created = register_document(s, a.source_id, Path(a.file), published=a.published)
            print(f"{'Registered' if created else 'Already registered'}: document {doc.id}, {doc.pages or '?'} pages, "
                  f"sha256 {doc.sha256[:12]}, {doc.raw_path}")
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
