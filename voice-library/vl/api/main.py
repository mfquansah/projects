"""Local web API + page. Binds to this computer only; never serves a file outside the audio folder.

`create_app` takes its dependencies as arguments so tests can pass fakes. Claude is part of the product: when it isn't
configured (no API key) the page says so and questions run as plain local search.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func

from vl import library as lib
from vl.ask import ask
from vl.db import Enrichment, Note, Transcript
from vl.enrich.query import LocalParser
from vl.index.search import Hit, search
from vl.ingest.importer import AUDIO_EXTS
from vl.peaks import peaks_for
from vl.snippets import best_snippet, query_terms
from vl.sounds.store import sounds_coverage
import os

from vl.batch import build_report, pick_new, remaining_audio_seconds
from vl.voicememos import PERMISSION_HELP, audio_files, find_voice_memos, newest_first

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
AUDIO_TYPES = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".aac": "audio/aac",
               ".caf": "audio/x-caf", ".qta": "video/quicktime"}
MAX_UPLOAD_BYTES = 2 * 1024 ** 3  # per file
MAX_UPLOAD_FILES = 500


def decorate(s, hits: list[Hit], terms: list[str]) -> list[dict]:
    """Hits as JSON for the page: tags, and the moment in the transcript that matched (with its timestamp)."""
    out = []
    for h in hits:
        en, tr = s.get(Enrichment, h.note_id), s.get(Transcript, h.note_id)
        snippet = None
        if terms and tr is not None:
            try:
                segs = json.loads(tr.segments_json or "[]")
            except ValueError:
                segs = []
            snippet = best_snippet(segs, tr.text, terms)
        out.append({
            "id": h.note_id, "title": h.title, "summary": h.summary, "category": h.category,
            "recorded_at": h.recorded_at.isoformat() if h.recorded_at else None, "duration_s": h.duration_s,
            "sound_info": h.sound_info, "sound_start_s": h.sound_start_s, "sound_conf": h.sound_conf, "why": h.why, "strength": h.strength,
            "tags": json.loads(en.tags_json) if en else [], "snippet": snippet,
        })
    return out


class AskBody(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=30)


class CategoryBody(BaseModel):
    name: str
    from_tag: str | None = None


class NameBody(BaseModel):
    name: str


class AssignBody(BaseModel):
    category_id: int | None = None


class FlagBody(BaseModel):
    flag: str | None = None  # "archived" | "keep" | null to clear


class FolderBody(BaseModel):
    path: str | None = None
    source: str | None = None  # "voice_memos"
    newest: int | None = Field(default=None, ge=1, le=500)  # a test batch: only the N newest recordings not yet imported


class SyncSettingsBody(BaseModel):
    enabled: bool | None = None
    interval_min: int | None = None


class DetailsBody(BaseModel):
    title: str | None = None
    summary: str | None = None
    tags: list[str] | None = None


def create_app(session_factory, embedder=None, parser=None, reranker=None, audio_root: Path | None = None,
               claude_unavailable_reason: str | None = None, import_manager=None, cache_dir: Path | None = None,
               upload_dir: Path | None = None, sync_manager=None) -> FastAPI:
    app = FastAPI(title="Voice Note Library", docs_url=None, redoc_url=None)
    # defend against DNS-rebinding: only answer requests addressed to this computer
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    claude_ok = parser is not None
    audio_root = Path(audio_root).resolve() if audio_root else None
    upload_dir = Path(upload_dir) if upload_dir else None
    sess = session_factory

    def guarded(fn):
        try:
            return fn()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    if WEB_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    def index():
        page = WEB_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(404, "web/index.html is missing")
        return FileResponse(page)

    @app.get("/api/settings")
    def get_settings():
        return {"claude": claude_ok,
                "reason": None if claude_ok else (claude_unavailable_reason or "Claude isn't connected.")}

    @app.get("/api/home")
    def home():
        with sess() as s:
            analyzed, total = sounds_coverage(s)
            att = lib.attention(s)
            return {"total_notes": total, "categories": lib.category_counts(s), "attention_count": att["count"],
                    "try": lib.try_queries(s, 3), "sounds_checked": analyzed}

    @app.get("/api/search")
    def quick_search(q: str = "", category: str | None = None, limit: int = 8):
        """Instant, local-only search (used while typing). Never calls Claude."""
        if not q.strip():
            return {"hits": []}
        with sess() as s:
            hits = search(s, q, embedder, limit=min(max(limit, 1), 30), category=category)
            return {"hits": decorate(s, hits, query_terms(q))}

    @app.get("/api/browse")
    def browse(category_id: int | None = None, uncategorized: bool = False, limit: int = 30, offset: int = 0):
        """Newest notes first, optionally one category. Local only."""
        with sess() as s:
            return {"hits": decorate(s, lib.list_notes(s, category_id, uncategorized, limit, offset), [])}

    @app.post("/api/ask")
    def ask_question(body: AskBody):
        with sess() as s:
            res = ask(s, body.q, parser if claude_ok else LocalParser(), embedder,
                      reranker if claude_ok else None, limit=body.limit)
            terms = query_terms(body.q, res.query.semantic_text, *res.query.keywords)
            hits = decorate(s, res.hits, terms)
        q = res.query
        notes = list(res.notes)
        if not claude_ok:
            notes.insert(0, (claude_unavailable_reason or "Claude isn't connected") +
                         " — this was a basic search, so dates, categories and ordering in the question aren't understood.")
        return {
            "hits": hits, "verdict": res.verdict, "notes": notes, "used_claude": claude_ok,
            "understood": {"topic": q.semantic_text, "category": q.category, "sort": q.sort, "count": q.count,
                           "sound": q.sound, "since": q.since.isoformat() if q.since else None,
                           "until": q.until.isoformat() if q.until else None},
        }

    @app.get("/api/notes/{note_id}")
    def note(note_id: int):
        with sess() as s:
            d = lib.note_detail(s, note_id)
            if d is None:
                raise HTTPException(404, "No such note")
            d["related"] = lib.related_notes(s, note_id, embedder.model_version) if embedder is not None else []
        return d

    @app.patch("/api/notes/{note_id}")
    def edit_note(note_id: int, body: DetailsBody):
        with sess() as s:
            return guarded(lambda: lib.update_details(s, note_id, body.title, body.summary, body.tags, embedder))

    @app.get("/api/notes/{note_id}/peaks")
    def peaks(note_id: int, n: int = 96):
        n = min(max(n, 16), 400)
        with sess() as s:
            row = s.get(Note, note_id)
            info = (Path(row.path), row.sha256) if row else None
        if info is None:
            raise HTTPException(404, "No such note")
        path, key = info
        if audio_root is not None and audio_root not in path.resolve().parents:
            raise HTTPException(403, "That file is outside the audio folder.")
        if not path.is_file():
            raise HTTPException(404, "The audio file is missing from disk.")
        try:
            return {"peaks": peaks_for(path, key, cache_dir, n)}
        except Exception as exc:  # noqa: BLE001 - the page falls back to a flat bar; don't break the note view
            raise HTTPException(500, f"Couldn't read the audio: {type(exc).__name__}") from exc

    @app.get("/api/notes/{note_id}/audio")
    def audio(note_id: int):
        with sess() as s:
            n = s.get(Note, note_id)
            path = Path(n.path).resolve() if n else None
        if path is None:
            raise HTTPException(404, "No such note")
        if audio_root is not None and audio_root not in path.parents:
            raise HTTPException(403, "That file is outside the audio folder.")
        if not path.is_file():
            raise HTTPException(404, "The audio file is missing from disk.")
        return FileResponse(path, media_type=AUDIO_TYPES.get(path.suffix.lower(), "application/octet-stream"))

    # ---- curation ----
    @app.get("/api/attention")
    def attention():
        with sess() as s:
            return {**lib.attention(s), "tags": lib.tag_counts(s, 20)}

    @app.post("/api/categories")
    def new_category(body: CategoryBody):
        with sess() as s:
            return guarded(lambda: lib.create_category(s, body.name, body.from_tag))

    @app.post("/api/suggestions/accept")
    def accept(body: NameBody):
        with sess() as s:
            return guarded(lambda: lib.accept_suggestion(s, body.name))

    @app.post("/api/suggestions/reject")
    def reject(body: NameBody):
        with sess() as s:
            return {"cleared": lib.reject_suggestion(s, body.name)}

    @app.post("/api/notes/{note_id}/category")
    def assign(note_id: int, body: AssignBody):
        with sess() as s:
            guarded(lambda: lib.assign_category(s, note_id, body.category_id))
        return {"ok": True}

    @app.post("/api/notes/{note_id}/flag")
    def flag(note_id: int, body: FlagBody):
        with sess() as s:
            if body.flag is None:
                lib.clear_flag(s, note_id)
            else:
                guarded(lambda: lib.set_flag(s, note_id, body.flag))
        return {"ok": True}

    @app.get("/api/review")
    def review():
        with sess() as s:
            return {"notes": lib.review_queue(s)}

    @app.get("/api/archived")
    def archived():
        with sess() as s:
            return {"notes": lib.archived_notes(s)}

    # ---- import ----
    @app.post("/api/import")
    async def import_files(files: list[UploadFile] = File(...), modified: list[int] = Form(default=[])):
        if import_manager is None or upload_dir is None:
            raise HTTPException(503, "Importing isn't available here.")
        if len(files) > MAX_UPLOAD_FILES:
            raise HTTPException(400, f"Please add at most {MAX_UPLOAD_FILES} files at a time.")
        batch = upload_dir / uuid.uuid4().hex[:10]
        batch.mkdir(parents=True, exist_ok=True)
        items, rejected = [], []
        for i, up in enumerate(files):
            name = Path(up.filename or "").name or f"file-{i}"
            if Path(name).suffix.lower() not in AUDIO_EXTS:
                rejected.append({"name": name, "reason": "Not an audio file I can read (.m4a, .mp3, .wav, .aac, .caf)."})
                continue
            dest = batch / f"{i}-{uuid.uuid4().hex[:6]}{Path(name).suffix.lower()}"
            size = 0
            try:
                with dest.open("wb") as out:
                    while chunk := await up.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_UPLOAD_BYTES:
                            raise ValueError("too big")
                        out.write(chunk)
            except ValueError:
                dest.unlink(missing_ok=True)
                rejected.append({"name": name, "reason": "That file is larger than 2 GB."})
                continue
            when = None
            if i < len(modified) and modified[i] > 0:
                try:
                    when = dt.datetime.fromtimestamp(modified[i] / 1000)
                except (OverflowError, OSError, ValueError):
                    when = None
            items.append((name, dest, when))
        if not items:
            shutil.rmtree(batch, ignore_errors=True)
            raise HTTPException(400, "None of those files were audio I can import.")
        return {"job_id": import_manager.submit(items), "accepted": len(items), "rejected": rejected}

    @app.get("/api/import/sources")
    def import_sources():
        """What can be imported straight from this computer (no uploading)."""
        return {"voice_memos": find_voice_memos()}

    @app.post("/api/import/folder")
    def import_folder_path(body: FolderBody):
        """Import audio from a folder on this computer (or the Voice Memos library). Files are read in place and never changed."""
        if import_manager is None:
            raise HTTPException(503, "Importing isn't available here.")
        if body.source == "voice_memos":
            info = find_voice_memos()
            if not info["found"]:
                raise HTTPException(403 if info["path"] else 404, info["problem"])
            folder = Path(info["path"])
        elif body.path and body.path.strip():
            folder = Path(body.path.strip()).expanduser()
            if not folder.is_dir():
                raise HTTPException(400, f"'{folder}' isn't a folder on this computer. Check the path (you can drag a folder into Terminal to see its path).")
        else:
            raise HTTPException(400, "Give a folder path, or choose Voice Memos.")
        try:
            files = audio_files(folder)
        except PermissionError:
            raise HTTPException(403, PERMISSION_HELP) from None
        if not files:
            raise HTTPException(400, f"No audio files (.m4a, .mp3, .wav, .aac, .caf) found in {folder}.")
        files = newest_first(files)   # newest first: recent recordings become searchable first
        total_files = len(files)
        if body.newest:
            with sess() as s:
                files = pick_new(files, body.newest, s)
            if not files:
                raise HTTPException(400, "Everything in that folder is already in your library.")
        items = []
        for p in files:
            try:
                when = dt.datetime.fromtimestamp(p.stat().st_mtime)
            except OSError:
                when = None
            items.append((p.name, p, when, False))  # False: never delete the original
        meta = {"folder": str(folder), "total_files": total_files, "batch": bool(body.newest)}
        return {"job_id": import_manager.submit(items, meta=meta), "accepted": len(items), "folder": str(folder), "batch": bool(body.newest)}

    @app.get("/api/import/{job_id}/report")
    def import_report(job_id: str):
        """Timing, Claude usage and an estimate for the rest, for a finished import (meant for test batches)."""
        snap = import_manager.snapshot(job_id) if import_manager else None
        if snap is None:
            raise HTTPException(404, "No such import")
        if not snap["finished"]:
            raise HTTPException(409, "That import is still running.")
        meta = snap.get("meta") or {}
        remaining_files, remaining_s = 0, None
        done_audio = [f["audio_s"] for f in snap["files"] if f["state"] == "done" and f.get("audio_s")]
        if meta.get("folder"):
            try:
                batch_names = {f["name"] for f in snap["files"]}
                rest = [p for p in audio_files(Path(meta["folder"])) if p.name not in batch_names]
                remaining_files = len(rest)
                remaining_s = remaining_audio_seconds(rest, (sum(done_audio) / len(done_audio)) if done_audio else None)
            except OSError:
                pass

        def price(name):
            try:
                return float(os.environ[name])
            except (KeyError, ValueError):
                return None

        rep = build_report(snap["files"], remaining_files, remaining_s, price("VL_PRICE_IN_PER_MTOK"), price("VL_PRICE_OUT_PER_MTOK"))
        rep["batch"] = bool(meta.get("batch"))
        rep["prices_set"] = price("VL_PRICE_IN_PER_MTOK") is not None and price("VL_PRICE_OUT_PER_MTOK") is not None
        return rep

    # ---- automatic sync with Voice Memos ----
    @app.get("/api/sync")
    def sync_status():
        if sync_manager is None:
            return {"available": False}
        return {"available": True, **sync_manager.status()}

    @app.post("/api/sync/settings")
    def sync_settings(body: SyncSettingsBody):
        if sync_manager is None:
            raise HTTPException(503, "Sync isn't available here.")
        return {"available": True, **guarded(lambda: sync_manager.set_settings(body.enabled, body.interval_min))}

    @app.post("/api/sync/run")
    def sync_run():
        if sync_manager is None:
            raise HTTPException(503, "Sync isn't available here.")
        sync_manager.trigger()
        return {"available": True, **sync_manager.status()}

    @app.get("/api/import/latest")
    def import_latest():
        return {"job": import_manager.latest() if import_manager else None}

    @app.get("/api/import/{job_id}")
    def import_status(job_id: str):
        snap = import_manager.snapshot(job_id) if import_manager else None
        if snap is None:
            raise HTTPException(404, "No such import")
        return snap

    @app.get("/api/health")
    def health():
        with sess() as s:
            return {"notes": s.query(func.count(Note.id)).scalar()}

    return app
