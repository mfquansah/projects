"""Load the curated source register and observation CSVs into the database.

Rebuilds from scratch each run (the CSVs in data/ are the source of truth for v0), by running the Alembic
migrations on a fresh database and then inserting. Fails loudly on malformed rows (see CLAUDE.md "Data rules").

Usage: python -m ingest.load [--db data/processed/monitor.sqlite]
"""
import argparse
import calendar
import csv
from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Entity, Observation, Source

ROOT = Path(__file__).resolve().parent.parent

SOURCE_COLS = ["source_id", "title", "publisher", "date", "url", "status",
               "contains", "reliability", "notes"]
OBS_COLS = ["year", "metric", "value", "unit", "period_type", "value_type",
            "source_id", "pdf_page", "confidence", "note"]

# The curated CSVs carry no capacity_type. Only an annual system peak maps to one: GRIDCo's annual peak is the
# coincident peak. Other metrics stay NULL rather than being guessed.
CAPACITY_TYPE_BY_METRIC = {"system_peak_demand": "peak_coincident"}


class LoadError(ValueError):
    pass


def source_tier(status: str) -> str:
    """Rule for the register: 'unreliable...' -> ai_summary; 'secondary' -> secondary; otherwise primary."""
    if status.startswith("unreliable"):
        return "ai_summary"
    if status == "secondary":
        return "secondary"
    return "primary"


def read_csv(path, expected_cols):
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header != expected_cols:
            raise LoadError(f"{path.name}: header {header} != expected {expected_cols}")
        rows = []
        for n, row in enumerate(reader, start=2):
            if not row:
                continue
            if len(row) != len(header):
                raise LoadError(f"{path.name} line {n}: {len(row)} columns, expected "
                                f"{len(header)} (unquoted comma?): {row[:2]}")
            rows.append(dict(zip(header, row)))
        return rows


def period_bounds(year: int, period_type: str):
    if period_type == "annual":
        return date(year, 1, 1), date(year, 12, 31)
    raise LoadError(f"period_type {period_type!r} not supported by the annual CSV loader")


def migrate(db_url: str):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


def load(db_path, data_dir=ROOT / "data"):
    sources = read_csv(data_dir / "source_register.csv", SOURCE_COLS)
    obs = read_csv(data_dir / "gridco_series.csv", OBS_COLS)

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    url = f"sqlite:///{db_path}"
    migrate(url)

    engine = create_engine(url)
    with Session(engine) as s, s.begin():
        s.add_all(Source(id=r["source_id"], name=r["title"], publisher=r["publisher"], url=r["url"],
                         tier=source_tier(r["status"]), notes=r["notes"], published=r["date"],
                         status=r["status"], contains=r["contains"], reliability=r["reliability"])
                  for r in sources)
        ghana = Entity(kind="national", name="Ghana")
        s.add(ghana)
        s.flush()
        for r in obs:
            start, end = period_bounds(int(r["year"]), r["period_type"])
            s.add(Observation(
                metric=r["metric"], entity_id=ghana.id, period_start=start, period_end=end,
                period_type=r["period_type"], value=float(r["value"]), unit=r["unit"],
                value_type=r["value_type"], capacity_type=CAPACITY_TYPE_BY_METRIC.get(r["metric"]),
                source_id=r["source_id"], page=r["pdf_page"], confidence=r["confidence"], note=r["note"]))
    with Session(engine) as s:
        n_src = len(s.scalars(select(Source)).all())
        n_obs = len(s.scalars(select(Observation)).all())
    engine.dispose()
    return n_src, n_obs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    args = ap.parse_args()
    s, o = load(args.db)
    print(f"Loaded {s} sources and {o} observations into {args.db}")
