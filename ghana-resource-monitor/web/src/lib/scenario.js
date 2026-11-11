// Browser copy of model/scenario.py. Keep the arithmetic identical; tests/vectors/scenario.json is shared by both.

/** @typedef {{base_year:number, base_peak:number, growth:number, end_year?:number, capacity_mw?:number|null,
 *   added_mw_per_year?:number, delay_years?:number, derate?:number, ev_fleet_base?:number, ev_growth?:number,
 *   ev_kw?:number, ev_coincidence?:number, ev_managed_share?:number, margin_target?:number}} Inputs */

/** @param {Inputs} i */
export function project(i) {
  const o = { end_year: 2040, capacity_mw: null, added_mw_per_year: 0, delay_years: 2, derate: 0, ev_fleet_base: 1200,
              ev_growth: 0.5, ev_kw: 7, ev_coincidence: 0.4, ev_managed_share: 0, margin_target: 0.18, ...i };
  const rows = [];
  for (let t = o.base_year; t <= o.end_year; t++) {
    const n = t - o.base_year;
    const demand = o.base_peak * (1 + o.growth) ** n;
    const ev_mw = (o.ev_fleet_base * (1 + o.ev_growth) ** n * o.ev_kw * o.ev_coincidence * (1 - o.ev_managed_share)) / 1000;
    const total = demand + ev_mw;
    let available = null, margin = null;
    if (o.capacity_mw !== null && o.capacity_mw !== undefined) {
      available = (o.capacity_mw + o.added_mw_per_year * Math.max(0, n - o.delay_years)) * (1 - o.derate);
      margin = available / total - 1;
    }
    rows.push({ year: t, demand, ev_mw, total, available, margin });
  }
  const first = (pred) => rows.find(pred)?.year ?? null;
  return {
    rows,
    below_target_year: first((r) => r.margin !== null && r.margin < o.margin_target),
    gap_year: first((r) => r.margin !== null && r.margin < 0),
  };
}

export function evsNeeded(shareOfPeak, basePeak, kw, coincidence, managedShare = 0) {
  return (shareOfPeak * basePeak) / ((kw * coincidence * (1 - managedShare)) / 1000);
}
