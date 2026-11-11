"""Load the source register and curated GRIDCo data into the database.

Rebuilds from scratch each run (the CSVs in data/ are the source of truth for v0): runs the Alembic migrations on a
fresh database, then inserts. Fails loudly on malformed rows (see CLAUDE.md "Data rules").

Inputs
- data/source_register.csv                    sources
- data/gridco/gridco_clean_2013_2025.csv      one chosen value per (year, metric), with the values rejected
- data/gridco_2025_extra.csv                  rows the clean file does not cover (2025 electricity access)

For every rejected value the loader stores it as its own observation (confidence low, `superseded_by` -> the chosen
row, so it never reaches the site as a live fact) and records a `conflicts` row linking both. Choices the data owner
marked "Unresolved" become open conflicts. Blank values are gaps and are never loaded.

Usage: python -m ingest.load [--db data/processed/monitor.sqlite]
"""
import argparse
import csv
import re
from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Conflict, Entity, Observation, Source

ROOT = Path(__file__).resolve().parent.parent

SOURCE_COLS = ["source_id", "title", "publisher", "date", "url", "status",
               "contains", "reliability", "notes"]
CLEAN_COLS = ["year", "metric", "value", "unit", "confidence", "source_file", "pdf_page", "method", "rejected_values"]
EXTRA_COLS = ["year", "metric", "value", "unit", "period_type", "value_type", "source_id", "pdf_page", "confidence", "note"]

# Only an annual system peak maps to a capacity_type: GRIDCo's annual peak is the coincident peak. Network asset
# metrics (e.g. transformation_capacity in MVA) are NOT generation capacity and stay NULL.
CAPACITY_TYPE_BY_METRIC = {"system_peak_demand": "peak_coincident"}
UNIT_NORMAL = {"%": "percent"}
REJECTED_RE = re.compile(r"^(?P<value>-?[\d.]+) \((?P<year>\d{4}) report p(?P<page>\d+)\)$")


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
            rows.append(dict(zip(header, row)))
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


def load(db_path, data_dir=ROOT / "data"):
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

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    url = f"sqlite:///{db_path}"
    migrate(url)

    gaps = []
    engine = create_engine(url)
    try:
        with Session(engine) as s, s.begin():
            s.add_all(Source(id=r["source_id"], name=r["title"], publisher=r["publisher"], url=r["url"],
                             tier=source_tier(r["status"]), notes=r["notes"], published=r["date"] or None,
                             status=r["status"], contains=r["contains"], reliability=r["reliability"])
                      for r in sources)
            ghana = Entity(kind="national", name="Ghana")
            s.add(ghana)
            s.flush()

            def make(year, metric, value, unit, confidence, source_id, page, note):
                return Observation(
                    metric=metric, entity_id=ghana.id, period_start=date(year, 1, 1), period_end=date(year, 12, 31),
                    period_type="annual", value=float(value), unit=UNIT_NORMAL.get(unit, unit), value_type="actual",
                    capacity_type=CAPACITY_TYPE_BY_METRIC.get(metric), source_id=source_id, page=page,
                    confidence=confidence, note=note)

            for r in clean:
                year = int(r["year"])
                if r["value"] == "":
                    gaps.append((year, r["metric"], r["method"]))  # a gap stays a gap
                    continue
                chosen = make(year, r["metric"], r["value"], r["unit"], r["confidence"],
                              source_for(report_year(r["source_file"])), r["pdf_page"], r["method"])
                s.add(chosen)
                s.flush()
                ids = [chosen.id]
                if r["rejected_values"]:
                    for part in r["rejected_values"].split("; "):
                        m = REJECTED_RE.match(part.strip())
                        if not m:
                            raise LoadError(f"{r['year']} {r['metric']}: cannot parse rejected value {part!r}")
                        rej = make(year, r["metric"], m["value"], r["unit"], "low", source_for(int(m["year"])), m["page"],
                                   f"Rejected in favour of {chosen.value:g}. {r['method']}")
                        rej.superseded_by = chosen.id  # never live: kept for the record
                        s.add(rej)
                        s.flush()
                        ids.append(rej.id)
                unresolved = "unresolved" in r["method"].lower()
                if len(ids) > 1 or unresolved:
                    s.add(Conflict(metric=r["metric"], entity_id=ghana.id, period=str(year), observation_ids=ids,
                                   status="open" if unresolved else "resolved", resolution_note=r["method"]))

            for r in extra:
                if r["period_type"] != "annual" or r["value_type"] != "actual":
                    raise LoadError("gridco_2025_extra.csv: only annual actuals are supported")
                s.add(make(int(r["year"]), r["metric"], r["value"], r["unit"], r["confidence"], r["source_id"],
                           r["pdf_page"], r["note"]))

        with Session(engine) as s:
            n_src = len(s.scalars(select(Source)).all())
            n_obs = len(s.scalars(select(Observation)).all())
    finally:
        engine.dispose()
    return n_src, n_obs, gaps


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    args = ap.parse_args()
    s, o, g = load(args.db)
    print(f"Loaded {s} sources and {o} observations into {args.db}")
    for y, m, why in g:
        print(f"  gap left blank: {y} {m} ({why})")
