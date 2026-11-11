"""Statistical baseline for annual system peak demand, with a rolling-origin backtest.

Deliberately simple: with only 13 annual actuals (GRIDCo 2013-2025) anything richer would overfit.
Note 2013-2016 were load-shedding years, so those peaks are what was delivered, not what was wanted.
Drivers (population, GDP, temperature) are phase-1b work once more history is ingested.

Usage: python -m model.baseline [--db data/processed/monitor.sqlite] [--horizon 7] [--no-store]
"""
import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Assumption, ForecastOutput, ModelRun, Observation

ROOT = Path(__file__).resolve().parent.parent
MODEL_VERSION = "baseline-0.2"
METRIC = "system_peak_demand"

# Two-sided 80% interval (p10..p90): Student-t 0.90 quantile by degrees of freedom (n - 2).
T90 = {1: 3.078, 2: 1.886, 3: 1.638, 4: 1.533, 5: 1.476, 6: 1.440, 7: 1.415, 8: 1.397, 9: 1.383, 10: 1.372,
       11: 1.363, 12: 1.356, 13: 1.350, 14: 1.345, 15: 1.341}


def _ols(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    xm, ym = x.mean(), y.mean()
    b = ((x - xm) * (y - ym)).sum() / ((x - xm) ** 2).sum()
    a = ym - b * xm
    return a, b


def predict_point(model: str, years, vals, target_years):
    """Point forecasts of `model` trained on (years, vals) for each target year.

    A model name is `<base>` or `<base>_w<N>`; the `_w<N>` form trains only on the last N points. Windows matter
    here: 2013-2016 were load-shedding years and 2016-2019 a rebound, so old points describe a different regime."""
    base, _, w = model.partition("_w")
    years, vals = list(years), list(vals)
    if w:
        years, vals = years[-int(w):], vals[-int(w):]
    last_y, last_v = years[-1], vals[-1]
    if base == "loglinear":  # constant growth rate fitted to the points used
        a, b = _ols(years, np.log(vals))
        return [math.exp(a + b * t) for t in target_years]
    if base == "linear":  # constant MW added per year
        a, b = _ols(years, vals)
        return [a + b * t for t in target_years]
    if base == "cagr_endpoints":  # growth from first to last point used
        g = (vals[-1] / vals[0]) ** (1 / (years[-1] - years[0]))
        return [last_v * g ** (t - last_y) for t in target_years]
    if base == "last_yoy":  # repeat the latest year-on-year growth
        g = vals[-1] / vals[-2]
        return [last_v * g ** (t - last_y) for t in target_years]
    raise ValueError(model)


MODELS = ("loglinear", "loglinear_w7", "loglinear_w5", "linear_w7", "cagr_endpoints_w7", "last_yoy")
MODEL_OF_RECORD = "loglinear"  # lowest backtest error (3.0% vs 6.9% for the 7-year window); see the Data and methods page
SENSITIVITY = "loglinear_w7"   # shown beside it: trend of the steady years only (2019 onward)
WINDOW = None                  # points used by the model of record (None = all)


def loglinear_interval(years, vals, target_years, window=None):
    """p10/p50/p90 from the log-linear fit (last `window` points if given) using a t-based prediction
    interval on log(peak)."""
    if window:
        years, vals = list(years)[-window:], list(vals)[-window:]
    x, y = np.asarray(years, float), np.log(vals)
    n = len(x)
    a, b = _ols(x, y)
    resid = y - (a + b * x)
    s = math.sqrt((resid ** 2).sum() / (n - 2))
    sxx = ((x - x.mean()) ** 2).sum()
    t = T90[min(n - 2, 15)]
    out = []
    for tgt in target_years:
        mu = a + b * tgt
        se = s * math.sqrt(1 + 1 / n + (tgt - x.mean()) ** 2 / sxx)
        out.append((math.exp(mu - t * se), math.exp(mu), math.exp(mu + t * se)))
    return out, {"annual_growth": math.exp(b) - 1, "resid_sd_log": s, "n": n}


def backtest(years, vals, min_train=7, max_h=3):
    """Rolling origin: train on the first k points, forecast each later year up to max_h ahead.
    Every model is scored on the same origins (min_train covers the widest window), so the comparison is fair."""
    rows = []
    for k in range(min_train, len(years)):
        ty, tv = years[:k], vals[:k]
        for h in range(1, max_h + 1):
            if k - 1 + h >= len(years):
                break
            target = years[k - 1 + h]
            actual = vals[k - 1 + h]
            for m in MODELS:
                p = predict_point(m, ty, tv, [target])[0]
                rows.append({"model": m, "origin": years[k - 1], "target": target, "h": h,
                             "forecast": p, "actual": actual, "ape": abs(p - actual) / actual})
    summary = {}
    for m in MODELS:
        mr = [r for r in rows if r["model"] == m]
        summary[m] = {"n": len(mr), "mape": float(np.mean([r["ape"] for r in mr])),
                      "mean_signed_error_pct": float(np.mean([(r["forecast"] - r["actual"]) / r["actual"] for r in mr]))}
    return summary, rows


def load_series(session):
    rows = session.execute(
        select(Observation.period_start, Observation.value, Observation.source_id).where(
            Observation.metric == METRIC, Observation.value_type == "actual",
            Observation.period_type == "annual", Observation.superseded_by.is_(None))
        .order_by(Observation.period_start)).all()
    years = [r.period_start.year for r in rows]
    if len(set(years)) != len(years):
        raise RuntimeError("more than one live peak value for a year; resolve the conflict first")
    # Each year's value comes from the annual report chosen for it, so there are several sources.
    return years, [r.value for r in rows], sorted({r.source_id for r in rows})


def run(db_path, horizon=7, store=True):
    engine = create_engine(f"sqlite:///{db_path}")
    with Session(engine) as s:
        years, vals, sources = load_series(s)
        summary, rows = backtest(years, vals)
        target_years = list(range(years[-1] + 1, years[-1] + 1 + horizon))
        intervals, fit = loglinear_interval(years, vals, target_years, window=WINDOW)
        sens = predict_point(SENSITIVITY, years, vals, target_years)
        result = {"model_version": MODEL_VERSION, "model_key": MODEL_OF_RECORD, "sources": sources, "history": dict(zip(years, vals)),
                  "fit": fit, "backtest": summary,
                  "sensitivity": {"model": SENSITIVITY, "points": dict(zip(target_years, sens))},
                  "forecast": {y: {"p10": lo, "p50": mid, "p90": hi}
                               for y, (lo, mid, hi) in zip(target_years, intervals)}}
        if store:
            with s.begin_nested():
                name = "baseline_peak_growth_loglinear"
                why = (f"Fitted log-linear growth of annual peak, {years[0]}-{years[-1]}; "
                       "not a policy or planning assumption.")
                row = s.scalars(select(Assumption).where(Assumption.name == name)).first()
                if row:
                    row.value, row.rationale = fit["annual_growth"], why
                else:
                    s.add(Assumption(name=name, value=fit["annual_growth"], unit="fraction/yr", rationale=why, source_id=None))
                scenario_json = {"kind": "baseline", "model": MODEL_OF_RECORD, "window_years": WINDOW,
                                 "interval": "80% prediction interval"}
                snapshot = {"metric": METRIC, "source_ids": sources, "series": dict(zip(map(str, years), vals))}
                prior = s.scalars(select(ModelRun).where(ModelRun.model_version == MODEL_VERSION)
                                  .order_by(ModelRun.id.desc())).first()
                if prior and prior.scenario_json == scenario_json and prior.inputs_snapshot == snapshot:
                    result["run_id"], result["reused_run"] = prior.id, True  # same inputs, same model: nothing new to store
                else:
                    run_row = ModelRun(model_version=MODEL_VERSION, scenario_json=scenario_json, inputs_snapshot=snapshot)
                    s.add(run_row)
                    s.flush()
                    for y, (lo, mid, hi) in zip(target_years, intervals):
                        s.add(ForecastOutput(run_id=run_row.id, metric=METRIC, period=str(y), p10=lo, p50=mid, p90=hi))
                    result["run_id"], result["reused_run"] = run_row.id, False
            s.commit()
    engine.dispose()
    return result


def report(res):
    f = res["fit"]
    lines = [f"Baseline {res['model_version']} on {len(res['history'])} annual peaks ({', '.join(res['sources'])})",
             f"Model of record {res['model_key']}: growth {f['annual_growth']*100:.2f}%/yr, residual sd {f['resid_sd_log']*100:.2f}% (log), n={f['n']} points",
             "", "Backtest (rolling origin, forecast 1-3 yrs ahead, same origins for every model):",
             f"  {'model':18}{'n':>3}{'MAPE':>8}{'bias':>8}"]
    for m, v in sorted(res["backtest"].items(), key=lambda kv: kv[1]["mape"]):
        lines.append(f"  {m:18}{v['n']:>3}{v['mape']*100:>7.1f}%{v['mean_signed_error_pct']*100:>+7.1f}%")
    lines += ["", "Forecast, annual peak MW (p10 / p50 / p90):"]
    for y, v in res["forecast"].items():
        lines.append(f"  {y}  {v['p10']:7.0f} / {v['p50']:7.0f} / {v['p90']:7.0f}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    ap.add_argument("--horizon", type=int, default=7)
    ap.add_argument("--no-store", action="store_true")
    ap.add_argument("--no-print", action="store_true")
    a = ap.parse_args()
    res = run(a.db, a.horizon, store=not a.no_store)
    if not a.no_print:
        print(report(res))
    print(f"model run {res.get('run_id')}{' (reused: inputs unchanged)' if res.get('reused_run') else ''}", file=sys.stderr)
