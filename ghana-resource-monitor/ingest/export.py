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

from db.models import Assumption, ForecastOutput, ModelRun, Observation, Source
from model.baseline import MODEL_VERSION, backtest, load_series
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
        first, last, prev = peaks[0], peaks[-1], peaks[-2]
        n = last["year"] - first["year"]
        derived = {
            "peak_latest": last["value"], "peak_latest_year": last["year"],
            "peak_yoy_pct": (last["value"] / prev["value"] - 1) * 100,
            "peak_growth_since_first_pct": (last["value"] / first["value"] - 1) * 100,
            "peak_first_year": first["year"],
            "peak_cagr_pct": ((last["value"] / first["value"]) ** (1 / n) - 1) * 100,
        }
        en = series["energy_transmitted"]
        derived["energy_latest"] = en[-1]["value"]
        derived["energy_yoy_pct"] = (en[-1]["value"] / en[-2]["value"] - 1) * 100

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
                "points": [{"year": int(f.period), "p10": f.p10, "p50": f.p50, "p90": f.p90} for f in fc],
                "backtest": bt,
            },
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
