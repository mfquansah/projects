"""Database models and session helpers (SQLite via SQLAlchemy 2.0)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from sqlalchemy import (
    DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, create_engine, event, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

SEED_CATEGORIES = [
    "Ideas",
    "Family memories",
    "Work & projects",
    "Personal reflections",
    "Other",
]


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    path: Mapped[str] = mapped_column(Text)  # path of the stored copy
    original_name: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    date_source: Mapped[str] = mapped_column(String(16), default="unknown")  # birthtime|mtime|filename|unknown
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    imported_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))


class Transcript(Base):
    __tablename__ = "transcripts"
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    segments_json: Mapped[str] = mapped_column(Text, default="[]")
    model_version: Mapped[str] = mapped_column(String(64))


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    # 'seed' | 'user' | 'suggested' (suggested ones are not used until accepted)
    origin: Mapped[str] = mapped_column(String(16), default="user")
    accepted: Mapped[bool] = mapped_column(default=True)


class Enrichment(Base):
    __tablename__ = "enrichment"
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    suggested_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    purpose: Mapped[str] = mapped_column(String(80), default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    junk_score: Mapped[float] = mapped_column(Float, default=0.0)
    model_version: Mapped[str] = mapped_column(String(64))


class Embedding(Base):
    __tablename__ = "embeddings"
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(64))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)


class SoundEvent(Base):
    """Empty until milestone 2 (sound tagging); present so the schema doesn't change later."""
    __tablename__ = "sound_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    label: Mapped[str] = mapped_column(String(64), index=True)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    model_version: Mapped[str] = mapped_column(String(64))


class Status(Base):
    """Per-note, per-stage state so reruns are resumable and failures are visible."""
    __tablename__ = "status"
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), primary_key=True)
    stage: Mapped[str] = mapped_column(String(16), primary_key=True)  # transcribe|enrich|index
    state: Mapped[str] = mapped_column(String(8))  # done|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


FTS_DDL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5("
    "title, summary, body, tags, note_id UNINDEXED)"
)


def make_session_factory(db_path: str | Path) -> sessionmaker[Session]:
    url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{db_path}"
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _):  # noqa: ANN001
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(FTS_DDL))
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        for name in SEED_CATEGORIES:
            if not s.query(Category).filter_by(name=name).first():
                s.add(Category(name=name, origin="seed", accepted=True))
        s.commit()
    return factory
