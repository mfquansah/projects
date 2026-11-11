"""Load the source register and curated observation CSVs into SQLite.

Rebuilds the database from scratch every run, so the CSVs in data/ stay the
single source of truth and the load is idempotent. Fails loudly on malformed
rows instead of guessing (see "Data rules" in CLAUDE.md).

Usage: python -m ingest.load [--db data/processed/monitor.sqlite]
"""
import argparse
import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "db" / "schema.sql"

SOURCE_COLS = ["source_id", "title", "publisher", "date", "url", "status",
               "contains", "reliability", "notes"]
OBS_COLS = ["year", "metric", "value", "unit", "period_type", "value_type",
            "source_id", "pdf_page", "confidence", "note"]

# The curated CSVs do not carry capacity_type. Only a peak-demand series maps to
# one: GRIDCo's annual system peak is the coincident peak. Other metrics stay NULL
# rather than being guessed.
CAPACITY_TYPE_BY_METRIC = {"system_peak_demand": "peak_coincident"}


class LoadError(ValueError):
    pass


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


def load(db_path, data_dir=ROOT / "data"):
    sources = read_csv(data_dir / "source_register.csv", SOURCE_COLS)
    obs = read_csv(data_dir / "gridco_series.csv", OBS_COLS)

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA.read_text())
    with con:
        con.executemany(
            f"INSERT INTO sources ({','.join(SOURCE_COLS)}) VALUES ({','.join('?' * len(SOURCE_COLS))})",
            [[r[c] for c in SOURCE_COLS] for r in sources])
        for r in obs:
            con.execute(
                """INSERT INTO observations
                   (metric, year, month, value, unit, period_type, value_type,
                    capacity_type, source_id, pdf_page, confidence, note)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["metric"], int(r["year"]), None, float(r["value"]), r["unit"],
                 r["period_type"], r["value_type"],
                 CAPACITY_TYPE_BY_METRIC.get(r["metric"]), r["source_id"],
                 r["pdf_page"], r["confidence"], r["note"]))
    n_src = con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    n_obs = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    con.close()
    return n_src, n_obs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    args = ap.parse_args()
    s, o = load(args.db)
    print(f"Loaded {s} sources and {o} observations into {args.db}")
