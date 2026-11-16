"""Background import: uploaded files go through the whole pipeline one at a time while the page shows progress.

One worker thread processes files in order, so only one transcription runs at once (Whisper is heavy). Each file
has a visible state; a failure on one file is shown on that file and never stops the others.
Heavy models are created lazily on first use (`deps`), so starting the server stays fast.
"""
from __future__ import annotations

import datetime as dt
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from vl.db import Category, Enrichment, Status
from vl.ingest.importer import import_one
from vl.pipeline import ProcessResult, process_note
from vl.sounds.store import analyze_note, record_sounds_error

# states, in the order a file moves through them
QUEUED, IMPORTING, TRANSCRIBING, TITLING, INDEXING, LISTENING = (
    "queued", "importing", "transcribing", "titling", "indexing", "listening")
DONE, DUPLICATE, ERROR = "done", "duplicate", "error"
FINISHED = {DONE, DUPLICATE, ERROR}
_STAGE_STATE = {"transcribe": TRANSCRIBING, "enrich": TITLING, "index": INDEXING}


@dataclass
class Deps:
    transcriber: object
    enricher: object
    embedder: object | None = None
    tagger: object | None = None  # sound detection; None = skip that step


@dataclass
class FileJob:
    name: str
    path: Path
    modified: dt.datetime | None = None
    delete_after: bool = True  # True for browser uploads (a temp copy); False for files imported in place: never delete originals
    state: str = QUEUED
    pct: int = 0
    note_id: int | None = None
    title: str = ""
    category: str = ""
    error: str = ""

    def public(self) -> dict:
        return {"name": self.name, "state": self.state, "pct": self.pct, "note_id": self.note_id,
                "title": self.title, "category": self.category, "error": self.error}


@dataclass
class Job:
    id: str
    files: list[FileJob] = field(default_factory=list)
    created: dt.datetime = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


class ImportManager:
    def __init__(self, session_factory, store_dir: Path, deps) -> None:
        """`deps` is a Deps, or a zero-argument function returning one (called once, on the first file)."""
        self._factory, self._store = session_factory, Path(store_dir)
        self._deps_src, self._deps = deps, None
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    # ---- public API ----
    def submit(self, items: list[tuple]) -> str:
        """items: (name the user knows, path, the file's own modified time or None[, delete_after]).

        delete_after defaults to True (a temporary upload). Pass False for files read from where they already live.
        """
        job = Job(id=uuid.uuid4().hex[:12], files=[
            FileJob(name=i[0], path=Path(i[1]), modified=i[2], delete_after=(i[3] if len(i) > 3 else True)) for i in items])
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
        for i in range(len(job.files)):
            self._q.put((job.id, i))
        self._ensure_worker()
        return job.id

    def snapshot(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return self._snap(job) if job else None

    def latest(self) -> dict | None:
        with self._lock:
            return self._snap(self._jobs[self._order[-1]]) if self._order else None

    def wait(self, timeout: float = 30.0) -> bool:
        """Block until everything queued so far is finished (used by tests). True if it finished in time."""
        done = threading.Event()

        def watcher():
            self._q.join()
            done.set()
        threading.Thread(target=watcher, daemon=True).start()
        return done.wait(timeout)

    # ---- internals ----
    @staticmethod
    def _snap(job: Job) -> dict:
        files = [f.public() for f in job.files]
        n = len(files)
        return {
            "id": job.id, "total": n, "files": files,
            "done": sum(f["state"] in (DONE, DUPLICATE) for f in files),
            "errors": sum(f["state"] == ERROR for f in files),
            "working": sum(f["state"] not in FINISHED and f["state"] != QUEUED for f in files),
            "waiting": sum(f["state"] == QUEUED for f in files),
            "finished": all(f["state"] in FINISHED for f in files),
        }

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name="vl-import", daemon=True)
                self._thread.start()

    def _get_deps(self) -> Deps:
        if self._deps is None:
            self._deps = self._deps_src() if callable(self._deps_src) else self._deps_src
        return self._deps

    def _set(self, f: FileJob, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(f, k, v)

    def _run(self) -> None:
        while True:
            try:
                job_id, idx = self._q.get(timeout=1.0)
            except queue.Empty:
                with self._lock:  # exit only under the lock submit() uses, so a file queued right now isn't stranded
                    if self._q.empty():
                        self._thread = None
                        return
                continue
            try:
                with self._lock:
                    f = self._jobs[job_id].files[idx]
                self._process(f)
            except Exception as exc:  # noqa: BLE001 - never let the worker die
                self._set(f, state=ERROR, error=f"{type(exc).__name__}: {exc}")
            finally:
                if f.delete_after:  # the library keeps its own copy of an upload; originals are never touched
                    try:
                        f.path.unlink(missing_ok=True)
                    except OSError:
                        pass
                self._q.task_done()

    def _process(self, f: FileJob) -> None:
        deps = self._get_deps()
        self._set(f, state=IMPORTING)
        with self._factory() as s:
            note, created = import_one(s, f.path, self._store, original_name=f.name, fallback_date=f.modified)
            self._set(f, note_id=note.id)
            if not created and s.get(Enrichment, note.id) is not None:
                en = s.get(Enrichment, note.id)
                cat = s.get(Category, en.category_id) if en.category_id else None
                self._set(f, state=DUPLICATE, title=en.title, category=cat.name if cat else "")
                return
            result = ProcessResult()
            process_note(s, note, deps.transcriber, deps.enricher, deps.embedder, result,
                         on_stage=lambda st: self._set(f, state=_STAGE_STATE[st], pct=0),
                         on_progress=lambda p: self._set(f, pct=p))
            if result.errors:
                bad = s.query(Status).filter_by(note_id=note.id, state="error").first()
                self._set(f, state=ERROR, error=(bad.error if bad else "processing failed"))
                return
            if deps.tagger is not None:
                self._set(f, state=LISTENING)
                try:
                    analyze_note(s, deps.tagger, note)
                except Exception as exc:  # noqa: BLE001 - sounds are a bonus; the note is still imported
                    record_sounds_error(s, note.id, exc)
            en = s.get(Enrichment, note.id)
            cat = s.get(Category, en.category_id) if en and en.category_id else None
            self._set(f, state=DONE, pct=100, title=en.title if en else "", category=cat.name if cat else "")
