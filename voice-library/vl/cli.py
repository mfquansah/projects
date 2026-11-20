"""Command line: `python -m vl.cli import|redate|process|sounds|serve|search|ask|evalgen|eval|status`.

Data lives in $VL_HOME (default ~/VoiceLibrary): library.db and audio/ (copies of imported files).
Original recordings are never modified or deleted.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from sqlalchemy import func

from vl.db import Enrichment, Note, Status, Transcript, make_session_factory
from vl.ingest.importer import AUDIO_EXTS, import_folder, redate_notes
from vl.pipeline import process_notes
from vl.index.search import search
from vl.sounds.store import run_sounds, sounds_coverage
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
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        raise SystemExit(f"'{folder}' is not a folder that exists. Check the path (drag the folder into Terminal to paste it).")
    with factory() as s:
        r = import_folder(s, folder, home() / "audio", args.limit)
    print(f"Imported {r.added}, skipped {r.skipped} already in library, failed {r.failed}.")
    if r.added + r.skipped + r.failed == 0:
        found = sorted({p.suffix.lower() or "(no extension)" for p in folder.rglob("*") if p.is_file()})
        print(f"No audio files found in {folder}. I look for: {', '.join(sorted(AUDIO_EXTS))}. "
              f"File types actually there: {', '.join(found) if found else 'none (the folder is empty)'}.")


def cmd_redate(_: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        changed, unchanged = redate_notes(s)
    print(f"Updated {changed} dates from filenames/audio metadata; left {unchanged} unchanged. Run `status` to review.")


def cmd_sounds(args: argparse.Namespace) -> None:
    from vl.sounds.tagger import AudioSetTagger

    if args.inspect:
        path = Path(args.inspect).expanduser()
        if not path.is_file():
            raise SystemExit(f"'{path}' is not a file. Give the path to one audio file (e.g. from ~/VoiceLibrary/audio/).")
        tagger = AudioSetTagger(threshold=args.threshold, device=args.device)
        for start, labels in tagger.inspect(path, windows=args.windows):
            print(f"\nWindow starting at {start:.0f}s: what the model hears (score 0-1, no cutoff applied)")
            for label, score in labels:
                print(f"  {score:5.2f}  {label}")
        return
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        if args.redo:
            from vl.db import Status as _Status
            s.query(_Status).filter_by(stage="sounds").delete()
            s.commit()
            print("Re-checking every note for sounds.")
        analyzed, total = sounds_coverage(s)
        print(f"{analyzed} of {total} notes already checked for sounds.")
        tagger = AudioSetTagger(threshold=args.threshold, device=args.device)
        r = run_sounds(s, tagger, limit=args.limit, progress=print)
    print(f"Checked {r['analyzed']} notes, found {r['events']} sound events, errors {r['errors']}.")


def cmd_profile(args: argparse.Namespace) -> None:
    """Time each stage on a few recordings, in a throwaway library (your real one is untouched)."""
    import time

    from vl.timing import format_profile, profile_files
    from vl.voicememos import audio_files, find_voice_memos, newest_first

    paths: list[Path] = []
    for raw in args.paths:
        p = Path(raw).expanduser()
        if p.is_dir():
            paths += newest_first(audio_files(p))
        elif p.is_file():
            paths.append(p)
        else:
            raise SystemExit(f"'{p}' is not a file or folder.")
    if args.voicememos:
        vm = find_voice_memos()
        if not vm["found"]:
            raise SystemExit(vm["problem"])
        paths += newest_first(audio_files(Path(vm["path"])))[: args.voicememos]
    paths = paths[: args.limit]
    if not paths:
        raise SystemExit("Give me recordings to time: file paths, a folder, or --voicememos 3.")

    loads: dict[str, float] = {}

    def timed(name, fn):
        t = time.perf_counter()
        obj = fn()
        loads[name] = time.perf_counter() - t
        return obj

    from vl.index.embeddings import SentenceTransformerEmbedder
    from vl.transcribe.whisper import FasterWhisperTranscriber

    transcriber = timed(f"Whisper ({args.whisper_model})", lambda: FasterWhisperTranscriber(args.whisper_model))
    embedder = timed("Embedding model", SentenceTransformerEmbedder)
    tagger = None
    if not args.no_sounds:
        from vl.sounds.tagger import AudioSetTagger

        tagger = timed("Sound model", lambda: AudioSetTagger(device=args.device))
    if args.no_claude or not os.environ.get("ANTHROPIC_API_KEY"):
        from vl.enrich.llm import EnrichmentResult

        class _Skip:
            model_version = "skipped"

            def enrich(self, transcript, categories, recorded_at):
                return EnrichmentResult(title="(skipped)", summary="", category="Other", model_version="skipped")

        if not args.no_claude:
            print("ANTHROPIC_API_KEY isn't set, so the Claude step is skipped (its time won't be measured).")
        enricher = _Skip()
    else:
        from vl.enrich.llm import ClaudeEnricher

        enricher = ClaudeEnricher(args.llm_model)
    print(f"Timing {len(paths)} recording(s) in a throwaway library. Your real library is not touched.\n")
    rows = profile_files(paths, transcriber, enricher, embedder, tagger, log=print)
    print("\n" + format_profile(rows, loads))


def cmd_serve(args: argparse.Namespace) -> None:
    if args.host not in ("127.0.0.1", "localhost"):
        raise SystemExit("For privacy the page only runs on this computer (127.0.0.1). "
                         "Phone access is planned but not built; it needs login first.")
    import uvicorn

    from vl.api.main import create_app
    from vl.enrich.llm import ClaudeEnricher
    from vl.enrich.query import ClaudeQueryParser, ClaudeReranker
    from vl.index.embeddings import SentenceTransformerEmbedder
    from vl.jobs import Deps, ImportManager

    parser = reranker = None
    reason = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        parser, reranker = ClaudeQueryParser(args.llm_model), ClaudeReranker(args.llm_model)
    else:
        reason = "Claude isn't connected (ANTHROPIC_API_KEY isn't set; set it and restart)"
    factory = make_session_factory(home() / "library.db")
    embedder = SentenceTransformerEmbedder()

    from vl.profile import load_name, save_name
    from vl.usage import UsageMeter

    display_name = save_name(home(), args.name) if args.name is not None else load_name(home())
    meter = UsageMeter()

    def import_deps() -> Deps:  # loaded on the first import, not at startup
        from vl.sounds.tagger import AudioSetTagger
        from vl.transcribe.whisper import FasterWhisperTranscriber

        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY isn't set, so titles and summaries can't be written. Set it and restart.")
        tagger = None
        try:
            tagger = AudioSetTagger()
        except Exception as exc:  # noqa: BLE001 - sounds are a bonus; imports still work without them
            print(f"  note: sound detection is unavailable ({type(exc).__name__}: {exc})")
        return Deps(FasterWhisperTranscriber(args.whisper_model), ClaudeEnricher(args.llm_model, meter=meter), embedder, tagger, meter=meter)

    from vl.sync import SyncManager

    sync_holder: dict = {}
    manager = ImportManager(factory, home() / "audio", import_deps,
                            on_file_done=lambda f: sync_holder["sync"].on_file_done(f))
    sync = sync_holder["sync"] = SyncManager(manager, home(), max_minutes=args.max_minutes)
    if sync.settings["enabled"]:
        sync.start()
    app = create_app(factory, embedder=embedder, parser=parser, reranker=reranker, audio_root=home() / "audio",
                     claude_unavailable_reason=reason, import_manager=manager,
                     cache_dir=home() / "cache" / "peaks", upload_dir=home() / "uploads", sync_manager=sync,
                     max_minutes=args.max_minutes, display_name=display_name, share_dir=home() / "shares")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Kasa Adaka running at {url}  (Ctrl+C to stop)")
    if reason:
        print(f"  note: {reason}")
    if args.open:
        import webbrowser
        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


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
    print(format_ask_result(res))


def format_ask_result(res) -> str:
    """Everything `ask` prints, as one string (kept separate from the command so it can be tested)."""
    q = res.query
    when = f"{q.since:%Y-%m-%d} to {q.until:%Y-%m-%d}" if q.since and q.until else (
        f"from {q.since:%Y-%m-%d}" if q.since else (f"before {q.until:%Y-%m-%d}" if q.until else "any date"))
    order = f" | order: {q.sort}" + (f" (top {q.count})" if q.count else "") if q.sort else ""
    lines = [f"Searching for: {q.semantic_text or 'any topic'} | category: {q.category or 'any'} | {when}{order}"]
    lines += [f"  note: {n}" for n in res.notes]
    if res.verdict:
        lines.append(f"Result: {res.verdict}")
    if not res.hits:
        lines.append("No matches.")
    for i, h in enumerate(res.hits, 1):
        d = h.recorded_at.strftime("%Y-%m-%d %H:%M") if h.recorded_at else "date unknown"
        length = f"  {int(h.duration_s // 60)}:{int(h.duration_s % 60):02d}" if h.duration_s else ""
        badge = {"match": "MATCH", "partial": "partial", "related": "related"}.get(h.strength or "")
        lines.append(f"{i}. {'<' + badge + '> ' if badge else ''}{h.title}  [{h.category or 'uncategorized'}]  {d}{length}"
                     f"\n   {h.summary}")
        if h.sound_info:
            lines.append(f"   sound: {h.sound_info}")
        if h.why:
            lines.append(f"   why: {h.why}")
        lines.append(f"   {h.path}")
    return "\n".join(lines)


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


def cmd_evalgen(args: argparse.Namespace) -> None:
    from vl.evalgen import (
        ClaudeQuestionWriter, absent_questions, content_questions, property_questions, review,
    )

    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        content, problems = content_questions(
            s, ClaudeQuestionWriter(args.llm_model), per_note=args.per_note, max_notes=args.max_notes)
        props, skipped = property_questions(s)
        absent = absent_questions(s)
    for p in problems + skipped:
        print(f"  note: {p}")
    questions = content + props + absent
    if not args.no_review and content:
        print("\nReview each question against the note it came from. The right answer is that note.")
        questions = review(questions)
    out = Path(args.out).expanduser()
    out.write_text(json.dumps({"questions": questions}, indent=2))
    kinds = {}
    for q in questions:
        kinds[q["kind"]] = kinds.get(q["kind"], 0) + 1
    print(f"\nWrote {len(questions)} questions to {out}: {kinds}")
    print(f"Next: python -m vl.cli eval {out}")


def cmd_status(_: argparse.Namespace) -> None:
    factory = make_session_factory(home() / "library.db")
    with factory() as s:
        total = s.query(func.count(Note.id)).scalar()
        print(f"Notes: {total}, transcribed: {s.query(func.count(Transcript.note_id)).scalar()}, "
              f"enriched: {s.query(func.count(Enrichment.note_id)).scalar()}")
        analyzed, total_n = sounds_coverage(s)
        print(f"Sounds checked: {analyzed} of {total_n}")
        by_src = dict(s.query(Note.date_source, func.count(Note.id)).group_by(Note.date_source).all())
        print(f"Date sources: {by_src}")
        weak = by_src.get("birthtime", 0) + by_src.get("mtime", 0)
        if weak:
            print(f"  Check dates by hand: {weak} note(s) use file times, which may be the EXPORT time, not when you recorded them.")
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

    a = sub.add_parser("sounds", help="detect baby crying/laughing etc. in imported notes")
    a.add_argument("--limit", type=int, help="check at most N notes (try 3 first: it can be slow)")
    a.add_argument("--threshold", type=float, default=0.10, help="lowest confidence to STORE (searches decide what counts; default 0.10)")
    a.add_argument("--redo", action="store_true", help="re-check every note, e.g. after lowering --threshold")
    a.add_argument("--device", default=None, help='e.g. "mps" on Apple Silicon (may be faster); default CPU')
    a.add_argument("--inspect", metavar="FILE", help="show what the model hears in ONE audio file (no cutoff), for debugging")
    a.add_argument("--windows", type=int, default=3, help="with --inspect: how many 10-second windows to show")
    a.set_defaults(func=cmd_sounds)

    a = sub.add_parser("serve", help="open the library in your browser (local only)")
    a.add_argument("--port", type=int, default=8765)
    a.add_argument("--host", default="127.0.0.1")
    a.add_argument("--open", action="store_true", help="open the page in your browser")
    a.add_argument("--llm-model", default="claude-haiku-5-5")
    a.add_argument("--whisper-model", default="small")
    a.add_argument("--name", default=None, help='your first name for the greeting, e.g. --name Michael (remembered in ~/VoiceLibrary/profile.json; --name "" removes it)')
    from vl.batch import DEFAULT_MAX_MINUTES
    a.add_argument("--max-minutes", type=float, default=DEFAULT_MAX_MINUTES,
                   help=f"skip recordings longer than this many minutes when importing from a folder or Voice Memos (default {DEFAULT_MAX_MINUTES}; 0 = no limit)")
    a.set_defaults(func=cmd_serve)

    a = sub.add_parser("profile", help="time each stage on a few recordings (nothing is added to your library)")
    a.add_argument("paths", nargs="*", help="audio files or folders")
    a.add_argument("--voicememos", type=int, metavar="N", help="also use the N newest Voice Memos recordings")
    a.add_argument("--limit", type=int, default=5, help="time at most this many recordings (default 5)")
    a.add_argument("--whisper-model", default="small")
    a.add_argument("--llm-model", default="claude-haiku-5-5")
    a.add_argument("--device", default=None, help="sound model device, e.g. mps (untested)")
    a.add_argument("--no-sounds", action="store_true", help="skip sound detection")
    a.add_argument("--no-claude", action="store_true", help="skip the Claude step (no key needed)")
    a.set_defaults(func=cmd_profile)

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

    a = sub.add_parser("evalgen", help="generate eval questions from your own notes")
    a.add_argument("--out", default="questions.json")
    a.add_argument("--per-note", type=int, default=2)
    a.add_argument("--max-notes", type=int, help="only use the first N notes")
    a.add_argument("--no-review", action="store_true", help="skip the keep/drop review (answers unchecked)")
    a.add_argument("--llm-model", default="claude-haiku-5-5")
    a.set_defaults(func=cmd_evalgen)

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
