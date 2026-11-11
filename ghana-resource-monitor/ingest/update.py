"""Incremental ingest: apply the curated inputs to a persistent database without ever rewriting history.

For every curated row, compared with the live row for the same fact (metric, period, source):
  new                 -> inserted
  identical           -> left alone
  value/metadata changed -> the old row is superseded (kept, marked) and the new one inserted (db.ops.supersede)
Rows already in the database but absent from the inputs are reported as warnings and never deleted.

Every real run is logged in `ingest_runs`. A failed run rolls back and is logged as failed (exit 1). With
--expect-changes a run that changes nothing exits 3, for scheduled jobs that should find new data. --dry-run
reports what would happen and writes nothing. Before a run that changes an existing SQLite database a snapshot
is copied to data/processed/backups/ (last 10 kept).

Usage: python -m ingest.update [--db PATH] [--dry-run] [--expect-changes] [--no-backup]
(DATABASE_URL overrides --db, for a hosted Postgres.)
"""
import argparse
import calendar
import hashlib
import math
import sqlite3
import sys
import traceback
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from db.models import Conflict, Entity, IngestRun, Observation, Source
from db.ops import supersede
from ingest.load import CAPACITY_TYPE_BY_METRIC, ROOT, LoadError, migrate, read_inputs, resolve_url, source_tier

BACKUPS_KEPT = 10
CHANGE_KEYS = ("entities_added", "entities_updated", "obs_inserted", "obs_superseded", "rejected_inserted", "conflicts_added", "conflicts_updated",
               "sources_added", "sources_updated")


@dataclass
class Result:
    status: str = "no_change"
    stats: Counter = field(default_factory=Counter)
    warnings: list = field(default_factory=list)
    gaps: list = field(default_factory=list)
    run_id: int | None = None
    dry_run: bool = False

    @property
    def changed(self) -> bool:
        return any(self.stats[k] for k in CHANGE_KEYS)


def _fact_key(o: Observation):
    return (o.metric, o.entity_id, o.period_start, o.period_end, o.period_type, o.value_type, o.capacity_type or "", o.source_id)


def _same(a: Observation, b: Observation) -> bool:
    return (math.isclose(a.value, b.value, abs_tol=1e-9) and a.unit == b.unit and a.confidence == b.confidence
            and a.page == b.page and a.note == b.note and a.capacity_type == b.capacity_type
            and a.table_ref == b.table_ref)


def _bounds(rec):
    if rec.period_type == "monthly":
        return date(rec.year, rec.month, 1), date(rec.year, rec.month, calendar.monthrange(rec.year, rec.month)[1])
    return date(rec.year, 1, 1), date(rec.year, 12, 31)


def _period_label(o: Observation) -> str:
    return f"{o.period_start.year}-{o.period_start.month:02d}" if o.period_type == "monthly" else str(o.period_start.year)


def apply(s: Session, sources, recs):
    """Apply parsed inputs inside the caller's transaction. Returns (stats, warnings). Never deletes."""
    st, warnings = Counter(), []

    have = {x.id: x for x in s.scalars(select(Source))}
    for r in sources:
        fields = dict(name=r["title"], publisher=r["publisher"], url=r["url"], tier=source_tier(r["status"]),
                      notes=r["notes"], published=r["date"] or None, status=r["status"], contains=r["contains"],
                      reliability=r["reliability"])
        cur = have.get(r["source_id"])
        if cur is None:
            s.add(Source(id=r["source_id"], **fields))
            st["sources_added"] += 1
        else:  # reference metadata (e.g. status 'to fetch' -> 'have') is updated in place
            changed = {k: v for k, v in fields.items() if getattr(cur, k) != v}
            for k, v in changed.items():
                setattr(cur, k, v)
            st["sources_updated"] += bool(changed)
    s.flush()

    # Entities: the national entity first, then anything the observation files name (plants, regions ...).
    entities = {(e.kind, e.name, e.parent_id): e for e in s.scalars(select(Entity))}
    ghana = entities.get(("national", "Ghana", None))
    if ghana is None:
        ghana = entities[("national", "Ghana", None)] = Entity(kind="national", name="Ghana")
        s.add(ghana)
        st["entities_added"] += 1
    s.flush()

    def entity_for(rec) -> Entity:
        if rec.entity_kind == "national" and rec.entity_name == "Ghana":
            return ghana
        if rec.parent_name:
            parents = [e for e in entities.values() if e.name == rec.parent_name]
            if len(parents) != 1:
                raise LoadError(f"{rec.entity_kind} {rec.entity_name!r}: parent {rec.parent_name!r} matches {len(parents)} entities")
            parent = parents[0]
        else:
            parent = ghana
        key = (rec.entity_kind, rec.entity_name, parent.id)
        attrs = {"fuel": rec.fuel} if rec.fuel else None
        e = entities.get(key)
        if e is None:
            e = entities[key] = Entity(kind=rec.entity_kind, name=rec.entity_name, parent_id=parent.id, attrs=attrs)
            s.add(e)
            s.flush()
            st["entities_added"] += 1
        elif attrs and e.attrs != attrs:  # entity descriptions (e.g. fuel) are reference data, updated in place
            e.attrs = attrs
            st["entities_updated"] += 1
        return e

    live = {_fact_key(o): o for o in s.scalars(select(Observation).where(Observation.superseded_by.is_(None)))}
    rejected_rows = {(o.metric, o.entity_id, o.period_start, o.source_id, o.value): o
                     for o in s.scalars(select(Observation).where(Observation.superseded_by.is_not(None)))}

    def make(rec, entity_id, value=None, confidence=None, source_id=None, page=None, note=None):
        start, end = _bounds(rec)
        return Observation(
            metric=rec.metric, entity_id=entity_id, period_start=start, period_end=end, period_type=rec.period_type,
            value=float(rec.value if value is None else value), unit=rec.unit, value_type=rec.value_type,
            capacity_type=rec.capacity_type or CAPACITY_TYPE_BY_METRIC.get(rec.metric),
            source_id=source_id or rec.source_id, page=rec.page if page is None else page,
            table_ref=rec.table_ref, confidence=confidence or rec.confidence, note=rec.note if note is None else note)

    conflicts = {(c.metric, c.entity_id, c.period): c for c in s.scalars(select(Conflict))}
    seen = set()
    for rec in recs:
        ent = entity_for(rec)
        new = make(rec, ent.id)
        key = _fact_key(new)
        cur = live.get(key)
        if cur is None:
            s.add(new)
            s.flush()
            st["obs_inserted"] += 1
            chosen = live[key] = new
        elif _same(cur, new):
            st["obs_unchanged"] += 1
            chosen = cur
        else:
            chosen = live[key] = supersede(s, cur, new)
            st["obs_superseded"] += 1
        seen.add(key)

        ids = [chosen.id]
        for rj in rec.rejected:
            ident = (rec.metric, ent.id, _bounds(rec)[0], rj.source_id, rj.value)
            row = rejected_rows.get(ident)
            if row is None:
                row = make(rec, ent.id, value=rj.value, confidence="low", source_id=rj.source_id, page=rj.page,
                           note=f"Rejected in favour of {chosen.value:g}. {rec.note}")
                row.superseded_by = chosen.id  # never live: kept for the record
                s.add(row)
                s.flush()
                rejected_rows[ident] = row
                st["rejected_inserted"] += 1
            ids.append(row.id)
        ckey = (rec.metric, ent.id, _period_label(chosen))
        c = conflicts.get(ckey)
        if len(ids) > 1 or rec.unresolved:
            status = "open" if rec.unresolved else "resolved"
            if c is None:
                c = conflicts[ckey] = Conflict(metric=rec.metric, entity_id=ent.id, period=ckey[2], observation_ids=ids,
                                               status=status, resolution_note=rec.note)
                s.add(c)
                st["conflicts_added"] += 1
            elif (c.observation_ids, c.status, c.resolution_note) != (ids, status, rec.note):
                c.observation_ids, c.status, c.resolution_note = ids, status, rec.note  # a conflict's status may change
                st["conflicts_updated"] += 1
        elif c is not None and c.status == "open" and not (c.resolution_note or "").startswith("Auto:"):
            c.observation_ids, c.status, c.resolution_note = ids, "resolved", rec.note  # no longer flagged: resolved
            st["conflicts_updated"] += 1

    # Different sources giving different live values for the same fact are kept side by side and flagged, never averaged.
    groups = defaultdict(list)
    for o in live.values():
        groups[(o.metric, o.entity_id, o.period_start, o.period_end, o.period_type, o.value_type, o.capacity_type)].append(o)
    for obs in groups.values():
        vals = [o.value for o in obs]
        disagree = len({o.source_id for o in obs}) > 1 and max(vals) - min(vals) > 1e-9
        ckey = (obs[0].metric, obs[0].entity_id, _period_label(obs[0]))
        c = conflicts.get(ckey)
        ids = sorted(o.id for o in obs)
        auto = c is not None and (c.resolution_note or "").startswith("Auto:")
        if disagree and c is None:
            span = ", ".join(f"{o.source_id}={o.value:g}" for o in sorted(obs, key=lambda o: o.source_id))
            conflicts[ckey] = Conflict(metric=ckey[0], entity_id=ckey[1], period=ckey[2], observation_ids=ids, status="open",
                                       resolution_note=f"Auto: sources disagree ({span}). Both are kept; nothing is averaged.")
            s.add(conflicts[ckey])
            st["conflicts_added"] += 1
        elif disagree and auto and (c.observation_ids, c.status) != (ids, "open"):
            c.observation_ids, c.status = ids, "open"
            st["conflicts_updated"] += 1
        elif not disagree and auto and c.status == "open":
            c.status, c.resolution_note, c.observation_ids = "resolved", "Auto: sources now agree.", ids
            st["conflicts_updated"] += 1

    metrics_in = {r.metric for r in recs}
    for key, o in live.items():
        if o.metric in metrics_in and key not in seen:
            warnings.append(f"live row not in the inputs (kept): {o.metric} {_period_label(o)} {o.source_id}")
    s.flush()
    return st, warnings


def _snapshot(url: str):
    """Copy the committed SQLite database to data/processed/backups/ and keep the newest BACKUPS_KEPT."""
    if not url.startswith("sqlite:///"):
        return None
    path = Path(url[len("sqlite:///"):])
    if not path.exists():
        return None
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    dest = folder / f"{path.stem}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%f}.sqlite"
    src, dst = sqlite3.connect(path), sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    for old in sorted(folder.glob(f"{path.stem}-*.sqlite"))[:-BACKUPS_KEPT]:
        old.unlink()
    return dest


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(url, data_dir=ROOT / "data", dry_run=False, backup=True, job="curated-csv") -> Result:
    """Migrate the database to the latest schema, then apply the curated inputs. See the module docstring."""
    data_dir = Path(data_dir)
    migrate(url)  # idempotent: also brings an older persistent database up to date
    engine = create_engine(url)
    res = Result(dry_run=dry_run)
    run_id = None
    try:
        if not dry_run:
            with Session(engine) as ls, ls.begin():
                row = IngestRun(job=job, status="running")
                ls.add(row)
                ls.flush()
                run_id = row.id
            res.run_id = run_id
        try:
            sources, recs, res.gaps = read_inputs(data_dir)
            with Session(engine) as s:  # plan pass: apply, then roll back
                had_data = s.scalar(select(func.count()).select_from(Observation)) > 0
                plan, res.warnings = apply(s, sources, recs)
                s.rollback()
            res.stats = plan
            if not dry_run:
                if res.changed and had_data and backup:
                    res.stats["backup"] = 1 if _snapshot(url) else 0
                with Session(engine) as s, s.begin():
                    res.stats, res.warnings = apply(s, sources, recs)
            res.status = "success" if res.changed else "no_change"
        except Exception:
            res.status = "failed"
            raise
        finally:
            if run_id is not None:
                inputs = {str(p.relative_to(data_dir)): _sha(p) for p in
                          [data_dir / "source_register.csv", data_dir / "gridco_2025_extra.csv",
                           data_dir / "gridco" / "gridco_clean_2013_2025.csv",
                           *sorted((data_dir / "observations").glob("*.csv"))] if p.exists()}
                err = traceback.format_exc() if res.status == "failed" else None
                with Session(engine) as ls, ls.begin():
                    row = ls.get(IngestRun, run_id)
                    row.status, row.finished_at = res.status, datetime.now(timezone.utc).replace(tzinfo=None)
                    row.rows_added = res.stats["obs_inserted"]
                    row.rows_superseded = res.stats["obs_superseded"]
                    row.rows_unchanged = res.stats["obs_unchanged"]
                    row.detail = {"stats": dict(res.stats), "warnings": res.warnings, "gaps": [list(g) for g in res.gaps],
                                  "input_sha256": inputs}
                    row.error = err[-4000:] if err else None
    finally:
        engine.dispose()
    return res


def summary(res: Result) -> str:
    st = res.stats
    lines = [f"{'DRY RUN: ' if res.dry_run else ''}status={res.status}",
             f"  entities: {st['entities_added']} added, {st['entities_updated']} updated",
             f"  observations: {st['obs_inserted']} inserted, {st['obs_superseded']} superseded, {st['obs_unchanged']} unchanged",
             f"  rejected values: {st['rejected_inserted']} stored; conflicts: {st['conflicts_added']} added, {st['conflicts_updated']} updated",
             f"  sources: {st['sources_added']} added, {st['sources_updated']} updated"]
    lines += [f"  warning: {w}" for w in res.warnings]
    lines += [f"  gap left blank: {y} {m}" for y, m, _ in res.gaps]
    if st["backup"]:
        lines.append("  snapshot saved to data/processed/backups/")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="SQLite path (default data/processed/monitor.sqlite)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--expect-changes", action="store_true", help="exit 3 if nothing changed (for scheduled jobs)")
    ap.add_argument("--no-backup", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = run(resolve_url(a.db), dry_run=a.dry_run, backup=not a.no_backup)
    except Exception as e:
        print(f"INGEST FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(summary(res))
    if a.expect_changes and not res.changed:
        print("ALERT: expected new data but nothing changed", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
