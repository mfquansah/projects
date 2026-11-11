"""Export database contents to JSON for the static site (and public download).

Every number the site shows comes from this file. Derived figures (growth rates etc.) are computed here,
not typed into templates. Fails if there is no stored forecast run, so a stale site cannot be built silently.

Usage: python -m ingest.export [--db data/processed/monitor.sqlite] [--out web/src/data/energy.json]
"""
import argparse
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Assumption, Conflict, ForecastOutput, ModelRun, Observation, Source
from model.baseline import MODEL_OF_RECORD, MODEL_VERSION, SENSITIVITY, backtest, load_series, predict_point
from model.scenario import ASSUMPTIONS, growth_cases

ROOT = Path(__file__).resolve().parent.parent


@contextmanager
def disposing(engine):
    try:
        yield engine
    finally:
        engine.dispose()


def export(db_path, out_path):
    engine = create_engine(f"sqlite:///{db_path}")
    with disposing(engine), Session(engine) as s:
        obs = s.scalars(select(Observation).where(Observation.superseded_by.is_(None))
                        .order_by(Observation.metric, Observation.period_start)).all()
        series = {}
        for o in obs:
            series.setdefault(o.metric, []).append({
                "year": o.period_start.year, "value": o.value, "unit": o.unit,
                "value_type": o.value_type, "capacity_type": o.capacity_type,
                "source_id": o.source_id, "page": o.page, "confidence": o.confidence, "note": o.note})

        run = s.scalars(select(ModelRun).where(ModelRun.model_version == MODEL_VERSION)
                        .order_by(ModelRun.id.desc())).first()
        if run is None:
            raise RuntimeError("no stored forecast run; run `python -m model.baseline` first")
        fc = s.scalars(select(ForecastOutput).where(ForecastOutput.run_id == run.id)
                       .order_by(ForecastOutput.period)).all()

        years, vals, _ = load_series(s)
        bt, _ = backtest(years, vals)
        peaks = series["system_peak_demand"]
        by_year = {p["year"]: p for p in peaks}
        SINCE = 2019  # GRIDCo's own headline comparison ("+52.7% since 2019")
        last, prev, ref = peaks[-1], peaks[-2], by_year[SINCE]
        en = series["energy_transmitted"]
        derived = {
            "peak_latest": last["value"], "peak_latest_year": last["year"],
            "peak_yoy_pct": (last["value"] / prev["value"] - 1) * 100,
            "peak_since_year": SINCE,
            "peak_growth_since_pct": (last["value"] / ref["value"] - 1) * 100,
            "peak_cagr_since_pct": ((last["value"] / ref["value"]) ** (1 / (last["year"] - SINCE)) - 1) * 100,
            "peak_first_year": peaks[0]["year"],
            "peak_cagr_full_pct": ((last["value"] / peaks[0]["value"]) ** (1 / (last["year"] - peaks[0]["year"])) - 1) * 100,
            "energy_latest": en[-1]["value"], "energy_latest_confidence": en[-1]["confidence"],
            "energy_yoy_pct": (en[-1]["value"] / en[-2]["value"] - 1) * 100,
            "energy_yoy_confidence": "low" if "low" in (en[-1]["confidence"], en[-2]["confidence"]) else en[-1]["confidence"],
        }
        target_years = [f.period for f in fc]
        sens = predict_point(SENSITIVITY, years, vals, [int(y) for y in target_years])
        by_id = {o.id: o for o in s.scalars(select(Observation)).all()}
        conflicts = []
        for c in s.scalars(select(Conflict).order_by(Conflict.metric, Conflict.period)).all():
            conflicts.append({
                "metric": c.metric, "year": int(c.period), "status": c.status, "note": c.resolution_note,
                "values": [{"value": by_id[i].value, "unit": by_id[i].unit, "source_id": by_id[i].source_id,
                            "page": by_id[i].page, "chosen": by_id[i].superseded_by is None} for i in c.observation_ids]})

        assumptions = s.scalars(select(Assumption).order_by(Assumption.name)).all()
        missing = set(ASSUMPTIONS) - {a.name for a in assumptions}
        if missing:
            raise RuntimeError(f"assumptions not seeded ({sorted(missing)}); run `python -m model.scenario` first")
        gc = growth_cases(years, vals)
        scenario = {
            "base_year": last["year"], "base_peak": last["value"], "end_year": 2040,
            "growth": {k: gc[k] for k in ("low", "central", "high")}, "growth_basis": gc["basis"],
            "assumptions": {a.name: {"value": a.value, "unit": a.unit, "rationale": a.rationale, "source_id": a.source_id}
                            for a in assumptions},
        }

        used = sorted({r["source_id"] for rows in series.values() for r in rows}
                      | {a.source_id for a in assumptions if a.source_id})
        sources = [{"id": x.id, "name": x.name, "publisher": x.publisher, "url": x.url, "tier": x.tier,
                    "status": x.status, "notes": x.notes}
                   for x in s.scalars(select(Source).where(Source.id.in_(used))).all()]

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "series": series,
            "derived": derived,
            "forecast": {
                "model_version": run.model_version, "run_at": run.run_at.isoformat(timespec="seconds"),
                "interval": run.scenario_json.get("interval"),
                "model_key": MODEL_OF_RECORD, "sensitivity_model": SENSITIVITY,
                "sensitivity": [{"year": int(y), "p50": v} for y, v in zip(target_years, sens)],
                "points": [{"year": int(f.period), "p10": f.p10, "p50": f.p50, "p90": f.p90} for f in fc],
                "backtest": bt,
            },
            "conflicts": conflicts,
            "scenario": scenario,
            "sources": sources,
            "capacity": None,  # no verified capacity yet; the site must show "not yet verified", never a number
        }
    engine.dispose()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    ap.add_argument("--out", default=str(ROOT / "web" / "src" / "data" / "energy.json"))
    a = ap.parse_args()
    p = export(a.db, a.out)
    print(f"Wrote {a.out}: {sum(len(v) for v in p['series'].values())} observations, "
          f"{len(p['forecast']['points'])} forecast years")
