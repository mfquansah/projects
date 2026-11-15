"""Command line: `python -m vl.cli import|process|search|status`.

Data lives in $VL_HOME (default ~/VoiceLibrary): library.db and audio/ (copies of imported files).
Original recordings are never modified or deleted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
from pathlib import Path

from sqlalchemy import func

from vl.db import Enrichment, Note, Status, Transcript, make_session_factory
from vl.ingest.importer import import_folder
from vl.pipeline import process_notes
from vl.index.search import search


def home() -> Path:
    p = Path(os.environ.get("VL_HOME", Path.home() / "VoiceLibrary"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cmd_import(args: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        r = import_folder(s, Path(args.folder).expanduser(), home() / "audio", args.limit)
    print(f"Imported {r.added}, skipped {r.skipped} already in library, failed {r.failed}.")


def cmd_process(args: argparse.Namespace) -> None:
    from vl.enrich.llm import ClaudeEnricher
    from vl.index.embeddings import SentenceTransformerEmbedder
    from vl.transcribe.whisper import FasterWhisperTranscriber

    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        r = process_notes(
            s, FasterWhisperTranscriber(args.whisper_model), ClaudeEnricher(args.llm_model),
            SentenceTransformerEmbedder(), limit=args.limit)
    print(f"Transcribed {r.transcribed}, enriched {r.enriched}, indexed {r.indexed}, errors {r.errors}.")
    if r.errors:
        print("Run `status` to see which notes failed and why.")


def cmd_search(args: argparse.Namespace) -> None:
    from vl.index.embeddings import SentenceTransformerEmbedder

    embedder = None if args.keyword_only else SentenceTransformerEmbedder()
    since = dt.datetime.fromisoformat(args.since) if args.since else None
    until = dt.datetime.fromisoformat(args.until) if args.until else None
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        hits = search(s, args.query, embedder, limit=args.limit, category=args.category, since=since, until=until)
    if not hits:
        print("No matches.")
    for i, h in enumerate(hits, 1):
        when = h.recorded_at.strftime("%Y-%m-%d %H:%M") if h.recorded_at else "date unknown"
        print(f"{i}. {h.title}  [{h.category or 'uncategorized'}]  {when}\n   {h.summary}\n   {h.path}")


def cmd_status(_: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        total = s.query(func.count(Note.id)).scalar()
        print(f"Notes: {total}, transcribed: {s.query(func.count(Transcript.note_id)).scalar()}, "
              f"enriched: {s.query(func.count(Enrichment.note_id)).scalar()}")
        for st in s.query(Status).filter_by(state="error"):
            note = s.get(Note, st.note_id)
            print(f"  ERROR {note.original_name} ({st.stage}): {st.error}")


def main() -> None:
    p = argparse.ArgumentParser(prog="vl")
    sub = p.add_subparsers(required=True)

    a = sub.add_parser("import", help="import audio files from a folder")
    a.add_argument("folder")
    a.add_argument("--limit", type=int, help="import at most N new files (use 25 for the pilot)")
    a.set_defaults(func=cmd_import)

    a = sub.add_parser("process", help="transcribe, enrich and index imported notes")
    a.add_argument("--limit", type=int)
    a.add_argument("--whisper-model", default="small")
    a.add_argument("--llm-model", default="claude-haiku-5-5")
    a.set_defaults(func=cmd_process)

    a = sub.add_parser("search", help="search the library")
    a.add_argument("query")
    a.add_argument("--category")
    a.add_argument("--since", help="ISO date, e.g. 2026-11-01")
    a.add_argument("--until", help="ISO date")
    a.add_argument("--limit", type=int, default=10)
    a.add_argument("--keyword-only", action="store_true", help="skip meaning search (no model download)")
    a.set_defaults(func=cmd_search)

    a = sub.add_parser("status", help="counts and any failures")
    a.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
