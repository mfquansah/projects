"""Local web API + page. Binds to this computer only; never serves a file outside the audio folder.

`create_app` takes its dependencies as arguments so tests can pass fakes. In real use `vl serve` supplies the real ones.
Privacy switch: with Claude off, `ask` runs entirely on this computer (plain search plus keyword sound inference).
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func

from vl import library as lib
from vl.ask import ask
from vl.db import Note
from vl.enrich.query import LocalParser
from vl.index.search import Hit, search
from vl.sounds.store import sounds_coverage

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
AUDIO_TYPES = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".aac": "audio/aac",
               ".caf": "audio/x-caf", ".qta": "video/quicktime"}


def hit_json(h: Hit) -> dict:
    return {
        "id": h.note_id, "title": h.title, "summary": h.summary, "category": h.category,
        "recorded_at": h.recorded_at.isoformat() if h.recorded_at else None, "duration_s": h.duration_s,
        "sound_info": h.sound_info, "sound_start_s": h.sound_start_s, "why": h.why, "strength": h.strength,
    }


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


class SettingsBody(BaseModel):
    use_claude: bool


def create_app(session_factory, embedder=None, parser=None, reranker=None, audio_root: Path | None = None,
               claude_unavailable_reason: str | None = None) -> FastAPI:
    app = FastAPI(title="Voice Note Library", docs_url=None, redoc_url=None)
    # defend against DNS-rebinding: only answer requests addressed to this computer
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.state.use_claude = parser is not None
    claude_possible = parser is not None
    audio_root = Path(audio_root).resolve() if audio_root else None

    def sess():
        return session_factory()

    @app.get("/")
    def index():
        page = WEB_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(404, "web/index.html is missing")
        return FileResponse(page)

    @app.get("/api/settings")
    def get_settings():
        return {"use_claude": app.state.use_claude, "claude_available": claude_possible,
                "reason": None if claude_possible else (claude_unavailable_reason or "No Claude key configured.")}

    @app.post("/api/settings")
    def set_settings(body: SettingsBody):
        if body.use_claude and not claude_possible:
            raise HTTPException(400, claude_unavailable_reason or "Claude isn't configured (set ANTHROPIC_API_KEY and restart).")
        app.state.use_claude = body.use_claude
        return get_settings()

    @app.get("/api/home")
    def home():
        with sess() as s:
            analyzed, total = sounds_coverage(s)
            return {
                "total_notes": total,
                "categories": lib.category_counts(s),
                "suggestions": lib.suggested_categories(s),
                "tags": lib.tag_counts(s, 20),
                "review_count": len(lib.review_queue(s)),
                "sounds_checked": analyzed,
            }

    @app.get("/api/search")
    def quick_search(q: str = "", category: str | None = None, limit: int = 8):
        """Instant, local-only search (used while typing). Never calls Claude."""
        if not q.strip():
            return {"hits": []}
        with sess() as s:
            return {"hits": [hit_json(h) for h in search(s, q, embedder, limit=min(max(limit, 1), 30),
                                                         category=category)]}

    @app.get("/api/browse")
    def browse(category_id: int | None = None, uncategorized: bool = False, limit: int = 30, offset: int = 0):
        """Newest notes first, optionally one category. Local only."""
        with sess() as s:
            return {"hits": [hit_json(h) for h in lib.list_notes(s, category_id, uncategorized, limit, offset)]}

    @app.post("/api/ask")
    def ask_question(body: AskBody):
        use = app.state.use_claude and claude_possible
        with sess() as s:
            res = ask(s, body.q, parser if use else LocalParser(), embedder, reranker if use else None,
                      limit=body.limit)
        q = res.query
        notes = list(res.notes)
        if not use:
            notes.insert(0, "Claude is off: this ran on your computer only, so dates, categories and ordering "
                            "in the question aren't understood.")
        return {
            "hits": [hit_json(h) for h in res.hits], "verdict": res.verdict, "notes": notes, "used_claude": use,
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
        return d

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

    def guarded(fn):
        try:
            return fn()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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

    @app.get("/api/health")
    def health():
        with sess() as s:
            return {"notes": s.query(func.count(Note.id)).scalar()}

    return app
