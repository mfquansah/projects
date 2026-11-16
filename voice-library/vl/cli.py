"""Command line: `python -m vl.cli import|redate|process|search|ask|eval|status`.

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
from vl.ingest.importer import import_folder, redate_notes
from vl.pipeline import process_notes
from vl.index.search import search
from vl.ask import ask
from vl.eval import (
    Counting, EvalSetError, check_expected_exist, format_report, load_questions, run_mode, to_json,
)


def home() -> Path:
    p = Path(os.environ.get("VL_HOME", Path.home() / "VoiceLibrary"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cmd_import(args: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        r = import_folder(s, Path(args.folder).expanduser(), home() / "audio", args.limit)
    print(f"Imported {r.added}, skipped {r.skipped} already in library, failed {r.failed}.")


def cmd_redate(_: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        changed, unchanged = redate_notes(s)
    print(f"Updated {changed} dates from filenames/audio metadata; left {unchanged} unchanged. Run `status` to review.")


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


def cmd_ask(args: argparse.Namespace) -> None:
    from vl.enrich.query import ClaudeQueryParser, ClaudeReranker
    from vl.index.embeddings import SentenceTransformerEmbedder

    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        res = ask(s, args.question, ClaudeQueryParser(args.llm_model), SentenceTransformerEmbedder(),
                  None if args.no_rerank else ClaudeReranker(args.llm_model), limit=args.limit)
    q = res.query
    when = f"{q.since:%Y-%m-%d} to {q.until:%Y-%m-%d}" if q.since and q.until else (
        f"from {q.since:%Y-%m-%d}" if q.since else (f"before {q.until:%Y-%m-%d}" if q.until else "any date"))
    print(f"Searching for: {q.semantic_text} | category: {q.category or 'any'} | {when}")
    for n in res.notes:
        print(f"  note: {n}")
    if not res.hits:
        print("No matches.")
    for i, h in enumerate(res.hits, 1):
        d = h.recorded_at.strftime("%Y-%m-%d %H:%M") if h.recorded_at else "date unknown"
        print(f"{i}. {h.title}  [{h.category or 'uncategorized'}]  {d}\n   {h.summary}")
        if h.why:
            print(f"   why: {h.why}")
        print(f"   {h.path}")


def cmd_eval(args: argparse.Namespace) -> None:
    from vl.enrich.query import ClaudeQueryParser, ClaudeReranker
    from vl.index.embeddings import SentenceTransformerEmbedder

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    unknown = set(modes) - {"search", "ask-norerank", "ask"}
    if unknown:
        raise SystemExit(f"Unknown mode(s): {', '.join(sorted(unknown))}. Choose from search, ask-norerank, ask.")
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        try:
            questions = load_questions(Path(args.questions).expanduser())
            check_expected_exist(s, questions)
        except EvalSetError as exc:
            raise SystemExit(f"Can't run the eval: {exc}")
        embedder = SentenceTransformerEmbedder()
        reports = []
        for mode in modes:
            parser = Counting(ClaudeQueryParser(args.llm_model), "parse") if mode != "search" else None
            reranker = Counting(ClaudeReranker(args.llm_model), "rerank") if mode == "ask" else None
            if mode == "search":
                def runner(q):
                    return search(s, q, embedder, limit=args.top), []
            else:
                def runner(q, parser=parser, reranker=reranker):
                    r = ask(s, q, parser, embedder, reranker, limit=args.top)
                    return r.hits, r.notes
            print(f"Running {len(questions)} questions in mode '{mode}'...")
            rep = run_mode(s, mode, runner, questions, top_k=args.top)
            rep.llm_calls = (parser.calls if parser else 0) + (reranker.calls if reranker else 0)
            reports.append(rep)
    print(format_report(reports))
    out = Path(args.out).expanduser() if args.out else home() / f"eval-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(to_json(reports, str(args.questions)))
    print(f"\nFull results saved to {out}")


def cmd_status(_: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        total = s.query(func.count(Note.id)).scalar()
        print(f"Notes: {total}, transcribed: {s.query(func.count(Transcript.note_id)).scalar()}, "
              f"enriched: {s.query(func.count(Enrichment.note_id)).scalar()}")
        by_src = dict(s.query(Note.date_source, func.count(Note.id)).group_by(Note.date_source).all())
        print(f"Date sources: {by_src}")
        if by_src.get("filename", 0) < total:
            print("  Check dates by hand: 'birthtime'/'mtime' may be the EXPORT time, not when you recorded the note.")
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

    a = sub.add_parser("redate", help="re-derive dates for imported notes from audio metadata")
    a.set_defaults(func=cmd_redate)

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

    a = sub.add_parser("ask", help="ask a question in plain language")
    a.add_argument("question")
    a.add_argument("--limit", type=int, default=5)
    a.add_argument("--no-rerank", action="store_true", help="skip the LLM rerank step")
    a.add_argument("--llm-model", default="claude-haiku-5-5")
    a.set_defaults(func=cmd_ask)

    a = sub.add_parser("eval", help="score search quality on a questions file")
    a.add_argument("questions", help="path to questions.json (see questions.example.json)")
    a.add_argument("--modes", default="search,ask-norerank,ask")
    a.add_argument("--top", type=int, default=5, help="results considered per question")
    a.add_argument("--out", help="where to save full results (default: ~/VoiceLibrary/eval-<time>.json)")
    a.add_argument("--llm-model", default="claude-haiku-5-5")
    a.set_defaults(func=cmd_eval)

    a = sub.add_parser("status", help="counts and any failures")
    a.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
