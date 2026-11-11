"""SQLAlchemy models for the Ghana Resource Monitor (schema from CLAUDE.md "Where data lives").

One schema for SQLite (local) and Postgres (production). Nothing here is SQLite-specific.
Observations are append-only: a correction inserts a new row and sets superseded_by on the old one.
"""
from datetime import date, datetime

from sqlalchemy import (JSON, CheckConstraint, Date, DateTime, Float, ForeignKey, Index,
                        Integer, String, Text, func)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _in(col, values):
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


TIERS = ("primary", "secondary", "ai_summary")
PERIOD_TYPES = ("annual", "monthly", "hourly")
VALUE_TYPES = ("actual", "forecast")
CAPACITY_TYPES = ("installed", "dependable", "available", "peak_coincident")
CONFIDENCE = ("high", "medium", "low")
ENTITY_KINDS = ("national", "plant", "region", "district", "vehicle_class")


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "S01"
    name: Mapped[str] = mapped_column(String, nullable=False)
    publisher: Mapped[str | None] = mapped_column(String)
    url: Mapped[str | None] = mapped_column(String)
    tier: Mapped[str] = mapped_column(String, nullable=False)
    licence: Mapped[str | None] = mapped_column(String)  # unknown until checked; never guessed
    notes: Mapped[str | None] = mapped_column(Text)
    # Fields carried over from the curated source register
    published: Mapped[str | None] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(String)
    contains: Mapped[str | None] = mapped_column(Text)
    reliability: Mapped[str | None] = mapped_column(String)
    __table_args__ = (CheckConstraint(_in("tier", TIERS), name="ck_sources_tier"),)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    raw_path: Mapped[str] = mapped_column(String, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    published_date: Mapped[date | None] = mapped_column(Date)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    pages: Mapped[int | None] = mapped_column(Integer)
    parse_status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    __table_args__ = (Index("uq_documents_source_sha", "source_id", "sha256", unique=True),)


class Entity(Base):
    __tablename__ = "entities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("entities.id"))
    geometry: Mapped[str | None] = mapped_column(Text)  # GeoJSON for now; PostGIS with the flood module
    attrs: Mapped[dict | None] = mapped_column(JSON)
    __table_args__ = (CheckConstraint(_in("kind", ENTITY_KINDS), name="ck_entities_kind"),
                      Index("uq_entities_kind_name_parent", "kind", "name", "parent_id", unique=True))


class Observation(Base):
    __tablename__ = "observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    value_type: Mapped[str] = mapped_column(String, nullable=False)
    capacity_type: Mapped[str | None] = mapped_column(String)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), nullable=False)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    page: Mapped[str | None] = mapped_column(String)  # text: can be "11, 25"
    table_ref: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    superseded_by: Mapped[int | None] = mapped_column(ForeignKey("observations.id"))
    __table_args__ = (
        CheckConstraint(_in("period_type", PERIOD_TYPES), name="ck_obs_period_type"),
        CheckConstraint(_in("value_type", VALUE_TYPES), name="ck_obs_value_type"),
        CheckConstraint("capacity_type IS NULL OR " + _in("capacity_type", CAPACITY_TYPES), name="ck_obs_capacity_type"),
        CheckConstraint(_in("confidence", CONFIDENCE), name="ck_obs_confidence"),
        CheckConstraint("period_end >= period_start", name="ck_obs_period_order"),
        # One live (non-superseded) fact per source; conflicts across sources coexist.
        # capacity_type is part of the identity: a plant's installed and dependable MW are different facts.
        # COALESCE because NULLs never collide in a plain unique index.
        Index("uq_obs_live_fact", "metric", "entity_id", "period_start", "period_end",
              "period_type", "value_type", func.coalesce(capacity_type, ""), "source_id", unique=True,
              sqlite_where=(superseded_by.is_(None)), postgresql_where=(superseded_by.is_(None))),
        Index("ix_obs_metric_period", "metric", "period_start"),
    )


class Conflict(Base):
    __tablename__ = "conflicts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"), nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    observation_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint(_in("status", ("open", "resolved")), name="ck_conflicts_status"),)


class Assumption(Base):
    __tablename__ = "assumptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"))


class ModelRun(Base):
    __tablename__ = "model_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    scenario_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    inputs_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ForecastOutput(Base):
    __tablename__ = "forecast_outputs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("model_runs.id"), nullable=False)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)
    p10: Mapped[float | None] = mapped_column(Float)
    p50: Mapped[float] = mapped_column(Float, nullable=False)
    p90: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (Index("uq_forecast_run_metric_period", "run_id", "metric", "period", unique=True),)


class IngestRun(Base):
    """One row per ingest run. status: running | success | no_change | failed."""
    __tablename__ = "ingest_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, nullable=False)
    rows_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_superseded: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    rows_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    detail: Mapped[dict | None] = mapped_column(JSON)  # full counters, warnings, input hashes
    error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint(_in("status", ("running", "success", "no_change", "failed")),
                                      name="ck_ingest_runs_status"),)


class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("observations.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    reviewer: Mapped[str | None] = mapped_column(String)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    __table_args__ = (CheckConstraint(_in("status", ("pending", "approved", "rejected")), name="ck_review_status"),)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric: Mapped[str] = mapped_column(String, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (CheckConstraint(_in("direction", ("above", "below")), name="ck_alert_rules_direction"),)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int] = mapped_column(ForeignKey("alert_rules.id"), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    payload: Mapped[dict | None] = mapped_column(JSON)
