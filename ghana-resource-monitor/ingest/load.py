"""Read the curated inputs (source register, cleaned GRIDCo series) and rebuild a database from them.

`read_inputs` parses and validates the CSVs. `ingest.update` applies them incrementally to a persistent database.
`load` (this module's CLI) is the dev/test shortcut: delete the database and apply everything to an empty one, so
there is only one code path for writing observations. Fails loudly on malformed rows (see CLAUDE.md "Data rules").

Inputs
- data/source_register.csv                    sources
- data/gridco/gridco_clean_2013_2025.csv      one chosen value per (year, metric), with the values rejected
- data/gridco_2025_extra.csv                  rows the clean file does not cover (2025 electricity access)

For every rejected value the update stores it as its own observation (confidence low, `superseded_by` -> the chosen
row, so it never reaches the site as a live fact) and records a `conflicts` row linking both. Choices the data owner
marked "Unresolved" become open conflicts. Blank values are gaps and are never loaded.

Usage: python -m ingest.load [--db data/processed/monitor.sqlite]
"""
import argparse
import csv
import re
import os
from dataclasses import dataclass, field
from pathlib import Path

import math
from alembic import command
from alembic.config import Config

from db.models import CAPACITY_TYPES, CONFIDENCE, ENTITY_KINDS, PERIOD_TYPES, VALUE_TYPES

ROOT = Path(__file__).resolve().parent.parent

SOURCE_COLS = ["source_id", "title", "publisher", "date", "url", "status",
               "contains", "reliability", "notes"]
CLEAN_COLS = ["year", "metric", "value", "unit", "confidence", "source_file", "pdf_page", "method", "rejected_values"]
# Free-form observations (plants, regions, monthly series, forecasts ...): one file per source or topic in data/observations/
OBS_FILE_COLS = ["entity_kind", "entity_name", "parent_name", "fuel", "metric", "period_type", "year", "month", "value",
                 "unit", "value_type", "capacity_type", "source_id", "page", "table_ref", "confidence", "note"]
EXTRA_COLS = ["year", "metric", "value", "unit", "period_type", "value_type", "source_id", "pdf_page", "confidence", "note"]

# Only an annual system peak maps to a capacity_type: GRIDCo's annual peak is the coincident peak. Network asset
# metrics (e.g. transformation_capacity in MVA) are NOT generation capacity and stay NULL.
CAPACITY_TYPE_BY_METRIC = {"system_peak_demand": "peak_coincident"}
UNIT_NORMAL = {"%": "percent"}
REJECTED_RE = re.compile(r"^(?P<value>-?[\d.]+) \((?P<year>\d{4}) report p(?P<page>\d+)\)$")


class LoadError(ValueError):
    pass


@dataclass
class Rejected:
    value: float
    source_id: str
    page: str


@dataclass
class Rec:
    """One chosen observation from the curated inputs, plus the values the data owner rejected for it."""
    year: int
    metric: str
    value: float
    unit: str
    confidence: str
    source_id: str
    page: str
    note: str
    rejected: list = field(default_factory=list)
    unresolved: bool = False
    # Defaults describe the GRIDCo national annual series; observation files set them explicitly.
    entity_kind: str = "national"
    entity_name: str = "Ghana"
    parent_name: str = ""
    fuel: str = ""
    period_type: str = "annual"
    month: int | None = None
    value_type: str = "actual"
    capacity_type: str | None = None
    table_ref: str | None = None


def resolve_url(db_path=None) -> str:
    """DATABASE_URL wins (hosted Postgres later); otherwise a local SQLite file."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return f"sqlite:///{Path(db_path or ROOT / 'data' / 'processed' / 'monitor.sqlite')}"


def source_tier(status: str) -> str:
    """Rule for the register: 'unreliable...' -> ai_summary; 'secondary' -> secondary; otherwise primary."""
    if status.startswith("unreliable"):
        return "ai_summary"
    if status == "secondary":
        return "secondary"
    return "primary"


def read_csv(path, expected_cols):
    with open(path, newline="", encoding="utf-8-sig") as f:
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
            rows.append({**dict(zip(header, row)), "_line": n})
        return rows


def migrate(db_url: str):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


def report_year(source_file: str) -> int:
    m = re.search(r"20\d\d", source_file)
    if not m:
        raise LoadError(f"cannot read a report year from file name {source_file!r}")
    return int(m.group())


def read_observation_files(data_dir, sources):
    """Validate and parse data/observations/*.csv. Every problem names the file and line."""
    by_id = {r["source_id"]: r for r in sources}
    recs = []
    for path in sorted((data_dir / "observations").glob("*.csv")):
        for r in read_csv(path, OBS_FILE_COLS):
            where = f"{path.name} line {r['_line']}"

            def bad(msg):
                raise LoadError(f"{where}: {msg}")

            def choice(field_, allowed, optional=False):
                v = r[field_].strip()
                if v == "" and optional:
                    return None
                if v not in allowed:
                    bad(f"{field_} {v!r} must be one of {list(allowed)}" + (" or blank" if optional else ""))
                return v

            kind = choice("entity_kind", ENTITY_KINDS)
            if not r["entity_name"].strip():
                bad("entity_name is required")
            if not r["metric"].strip() or not r["unit"].strip():
                bad("metric and unit are required")
            ptype = choice("period_type", PERIOD_TYPES)
            if ptype == "hourly":
                bad("hourly periods are not supported yet")
            try:
                year = int(r["year"])
                value = float(r["value"])
            except ValueError:
                bad(f"year {r['year']!r} and value {r['value']!r} must be numbers (a blank value is a gap: leave the row out)")
            if not (1900 <= year <= 2100) or not math.isfinite(value):
                bad("year out of range or value not finite")
            month = None
            if ptype == "monthly":
                if not r["month"].strip().isdigit() or not 1 <= int(r["month"]) <= 12:
                    bad(f"monthly rows need month 1-12, got {r['month']!r}")
                month = int(r["month"])
            elif r["month"].strip():
                bad("month must be blank unless period_type is monthly (never mix a monthly and an annual value)")
            src = r["source_id"].strip()
            if src not in by_id:
                bad(f"source {src!r} is not in data/source_register.csv")
            if source_tier(by_id[src]["status"]) == "ai_summary":
                bad(f"source {src} is an AI-generated summary and may not be cited")
            if not r["page"].strip():
                bad("page is required: every value must say where in the source it came from")
            recs.append(Rec(
                year=year, metric=r["metric"].strip(), value=value, unit=UNIT_NORMAL.get(r["unit"].strip(), r["unit"].strip()),
                confidence=choice("confidence", CONFIDENCE), source_id=src, page=r["page"].strip(), note=r["note"],
                entity_kind=kind, entity_name=r["entity_name"].strip(), parent_name=r["parent_name"].strip(),
                fuel=r["fuel"].strip(), period_type=ptype, month=month,
                value_type=choice("value_type", VALUE_TYPES), capacity_type=choice("capacity_type", CAPACITY_TYPES, optional=True),
                table_ref=r["table_ref"].strip() or None))
    return recs


def read_inputs(data_dir=ROOT / "data"):
    """Parse and validate the curated CSVs. Touches no database. Returns (source rows, records, gaps)."""
    sources = read_csv(data_dir / "source_register.csv", SOURCE_COLS)
    clean = read_csv(data_dir / "gridco" / "gridco_clean_2013_2025.csv", CLEAN_COLS)
    extra = read_csv(data_dir / "gridco_2025_extra.csv", EXTRA_COLS)

    by_report = {}  # report year -> GRIDCo annual report source id
    for r in sources:
        m = re.fullmatch(r"(\d{4}) Annual Report", r["title"])
        if m and r["publisher"] == "GRIDCo":
            by_report[int(m.group(1))] = r["source_id"]

    def source_for(year: int) -> str:
        if year not in by_report:
            raise LoadError(f"no GRIDCo {year} Annual Report in the source register")
        return by_report[year]

    ids = {r["source_id"] for r in sources}
    recs, gaps = [], []
    for r in clean:
        year = int(r["year"])
        if r["value"] == "":
            gaps.append((year, r["metric"], r["method"]))  # a gap stays a gap
            continue
        rec = Rec(year=year, metric=r["metric"], value=float(r["value"]), unit=UNIT_NORMAL.get(r["unit"], r["unit"]),
                  confidence=r["confidence"], source_id=source_for(report_year(r["source_file"])),
                  page=r["pdf_page"], note=r["method"], unresolved="unresolved" in r["method"].lower())
        if r["rejected_values"]:
            for part in r["rejected_values"].split("; "):
                m = REJECTED_RE.match(part.strip())
                if not m:
                    raise LoadError(f"{r['year']} {r['metric']}: cannot parse rejected value {part!r}")
                rec.rejected.append(Rejected(float(m["value"]), source_for(int(m["year"])), m["page"]))
        recs.append(rec)
    for r in extra:
        if r["period_type"] != "annual" or r["value_type"] != "actual":
            raise LoadError("gridco_2025_extra.csv: only annual actuals are supported")
        if r["source_id"] not in ids:
            raise LoadError(f"gridco_2025_extra.csv: unknown source {r['source_id']}")
        recs.append(Rec(year=int(r["year"]), metric=r["metric"], value=float(r["value"]),
                        unit=UNIT_NORMAL.get(r["unit"], r["unit"]), confidence=r["confidence"],
                        source_id=r["source_id"], page=r["pdf_page"], note=r["note"]))
    recs += read_observation_files(data_dir, sources)
    return sources, recs, gaps


def load(db_path, data_dir=ROOT / "data"):
    """Dev/test shortcut: delete the database and apply the inputs to an empty one. Returns (sources, observations, gaps)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from db.models import Observation, Source
    from ingest.update import run

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    url = f"sqlite:///{db_path}"
    result = run(url, data_dir, backup=False, job="rebuild")
    engine = create_engine(url)
    try:
        with Session(engine) as s:
            return (len(s.scalars(select(Source)).all()), len(s.scalars(select(Observation)).all()), result.gaps)
    finally:
        engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=load.__doc__)
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    args = ap.parse_args()
    s, o, g = load(args.db)
    print(f"Rebuilt {args.db}: {s} sources and {o} observations")
    for y, m, why in g:
        print(f"  gap left blank: {y} {m} ({why})")
