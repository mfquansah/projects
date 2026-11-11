"""Scenario model: when does demand (plus EV charging) pass available supply?

Capacity is an INPUT, not data: until plant capacity is verified from primary documents the model never
supplies a default. With no capacity given it still projects demand and EV load, but reports no gap year.

The same arithmetic is implemented in web/src/lib/scenario.js for the browser. tests/vectors/scenario.json holds
shared cases that both implementations must reproduce.

    available(t)  = (capacity + added_per_year * max(0, t - base_year - delay_years)) * (1 - derate)
    demand(t)     = base_peak * (1 + growth) ** (t - base_year)
    ev_mw(t)      = ev_fleet0 * (1 + ev_growth) ** (t - base_year) * kw * coincidence * (1 - managed_share) / 1000
    margin(t)     = available / (demand + ev_mw) - 1
"""
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Assumption
from model.baseline import load_series, loglinear_interval

ROOT = Path(__file__).resolve().parent.parent

# Model inputs that are NOT data. Each is stored in the `assumptions` table with its reason.
# name: (value, unit, rationale, source_id)
ASSUMPTIONS = {
    "ev_fleet_base": (1200, "vehicles", "Pure battery EVs registered by Oct 2025 per a DVLA figure quoted by UN Ghana (S09). "
                      "Secondary source; definitions conflict with other counts (e.g. ~17,000 incl. 2/3-wheelers). "
                      "Replace with DVLA primary data.", "S09"),
    "ev_growth": (0.5, "fraction/yr", "ILLUSTRATIVE. No source. A deliberately fast rate for a small fleet; "
                  "a slider, not a forecast.", None),
    "ev_kw_per_vehicle": (7.0, "kW", "ILLUSTRATIVE. A typical single-phase AC home or workplace charger.", None),
    "ev_coincidence": (0.4, "fraction", "ILLUSTRATIVE. Share of EVs charging at the moment of system peak. "
                       "No Ghana charging-load data exists yet.", None),
    "ev_managed_share": (0.0, "fraction", "Share of charging moved away from the peak hours (a policy lever). Default none.", None),
    "reserve_margin_target": (0.18, "fraction", "Benchmark quoted in the project brief (CLAUDE.md). Source to be verified.", None),
    "capacity_addition_delay": (2, "years", "ILLUSTRATIVE. Years before the first new capacity arrives; projects slip.", None),
}


@dataclass
class Inputs:
    base_year: int
    base_peak: float
    growth: float
    end_year: int = 2040
    capacity_mw: Optional[float] = None
    added_mw_per_year: float = 0.0
    delay_years: int = 2
    derate: float = 0.0
    ev_fleet_base: float = 1200
    ev_growth: float = 0.5
    ev_kw: float = 7.0
    ev_coincidence: float = 0.4
    ev_managed_share: float = 0.0
    margin_target: float = 0.18


def project(i: Inputs):
    rows = []
    for t in range(i.base_year, i.end_year + 1):
        n = t - i.base_year
        demand = i.base_peak * (1 + i.growth) ** n
        ev = i.ev_fleet_base * (1 + i.ev_growth) ** n * i.ev_kw * i.ev_coincidence * (1 - i.ev_managed_share) / 1000
        total = demand + ev
        avail = margin = None
        if i.capacity_mw is not None:
            avail = (i.capacity_mw + i.added_mw_per_year * max(0, n - i.delay_years)) * (1 - i.derate)
            margin = avail / total - 1
        rows.append({"year": t, "demand": demand, "ev_mw": ev, "total": total, "available": avail, "margin": margin})
    below_target = next((r["year"] for r in rows if r["margin"] is not None and r["margin"] < i.margin_target), None)
    gap = next((r["year"] for r in rows if r["margin"] is not None and r["margin"] < 0), None)
    return {"rows": rows, "below_target_year": below_target, "gap_year": gap}


def evs_needed(share_of_peak: float, base_peak: float, kw: float, coincidence: float, managed_share: float = 0.0):
    """Vehicles whose coincident charging load equals `share_of_peak` of the base peak."""
    per_vehicle_mw = kw * coincidence * (1 - managed_share) / 1000
    return share_of_peak * base_peak / per_vehicle_mw


def growth_cases(years, vals, window=3):
    """Low / central / high annual growth derived from the data: the slowest and fastest rolling
    `window`-year compound growth actually observed, and the log-linear fit as central."""
    cagr = [(vals[k] / vals[k - window]) ** (1 / window) - 1 for k in range(window, len(vals))]
    _, fit = loglinear_interval(years, vals, [years[-1] + 1])
    central = fit["annual_growth"]
    return {"low": min(cagr + [central]), "central": central, "high": max(cagr + [central]),
            "basis": f"slowest / fastest {window}-year compound growth observed, and the log-linear fit",
            "window_cagrs": cagr}


def seed_assumptions(session: Session):
    existing = {a.name for a in session.scalars(select(Assumption)).all()}
    for name, (value, unit, why, src) in ASSUMPTIONS.items():
        if name not in existing:
            session.add(Assumption(name=name, value=float(value), unit=unit, rationale=why, source_id=src))
    session.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "processed" / "monitor.sqlite"))
    a = ap.parse_args()
    engine = create_engine(f"sqlite:///{a.db}")
    with Session(engine) as s:
        seed_assumptions(s)
        years, vals, _ = load_series(s)
        g = growth_cases(years, vals)
        print(f"Seeded {len(ASSUMPTIONS)} assumptions. Growth cases: low {g['low']:.2%}, central {g['central']:.2%}, high {g['high']:.2%}")
    engine.dispose()
