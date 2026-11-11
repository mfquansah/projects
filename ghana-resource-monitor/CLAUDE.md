# Ghana Resource Monitor

A public platform that tracks, forecasts and warns about stress on Ghana's critical resources.
Phase 1 is **energy**: when does peak demand exceed the capacity Ghana can reliably deliver?
Later modules: flooding (climate vs. urbanization), heat, water bodies / galamsey.

## Core question (Phase 1)
Under realistic scenarios, when does peak electricity demand exceed *available* generation capacity,
and what levers (gas, new plants, EV charging, cooling, demand management) change that date?

## Architecture (four layers)
1. **Data repository**: database + raw file store. Every value carries provenance (see Data rules).
   Scheduled jobs ingest new data (PURC monthly, GRIDCo/Energy Commission annual; weather/satellite later).
   A small API server fronts the database for the site and the assistant.
2. **Forecast engine**: (a) statistical baseline for peak demand and energy (trend + drivers: population,
   GDP, temperature), backtested against history; (b) scenario model:
   `available = dependable - gas_shortfall - hydro_shortfall - maintenance - forced_outages`,
   with levers (new capacity with slippage, gas supply, EV adoption, cooling load, 24-hour economy).
   Output: year/month a gap opens, with ranges.
3. **Assistant (LLM)**: does NOT invent forecasts. It calls the forecast engine and database as tools,
   explains results, cites sources, states uncertainty. Questions like "what does the next two years look like?"
   and "what can we do about it?" run the model and the levers.
4. **Website**: "right now" page, forecast page with scenario sliders, ask box, methods page, data downloads.

## Phases
0. Verified dataset v0 (started: see data/)  1. Forecast model + backtest  2. Site v0
3. Assistant  4. Scheduled ingestion + alerts  5. Flood module (CHIRPS/GPM rainfall, Sentinel-1 flood extent,
urban growth / impervious surface, drainage; separate climate vs. urbanization effects).

## Data rules (non-negotiable)
- Every number records: value, unit, year (and month if applicable), source, page/table, and
  `value_type` (actual | forecast), `capacity_type` (installed | dependable | available | peak_coincident),
  `period_type` (annual | monthly | hourly), and a confidence note.
- Never mix a monthly peak with an annual peak. Never treat a forecast as an actual.
- Conflicting sources are stored side by side and flagged, not averaged.
- Prefer primary documents (GRIDCo, Energy Commission, PURC, Ministry of Energy, VRA, BPA, DVLA) over news/AI summaries.
- Do not fill gaps from memory.

## Verified so far (GRIDCo 2025 Annual Report, pp. 25-26)
Annual system peak (MW): 2019 2,804; 2020 3,090; 2021 3,246; 2022 3,469; 2023 3,618; 2024 3,952; **2025 4,283**.
2025 energy transmitted 25,860 GWh (+9.15%); transmission losses 4.02%. See data/gridco_series.csv.

## Known discrepancies / traps (found while reviewing an AI-generated research report)
- Installed capacity appears as ~5,200, 5,260, 5,507, 5,818 and "just under 6,000" MW: different boundaries
  (NITS-only vs embedded, dates, legacy non-operational plants). Reconcile plant by plant; don't pick one.
- 2025 peak: GRIDCo = 4,283 MW. A 4,125 MW figure is an Energy Commission *forecast*, not an actual.
  A July 2026 monthly peak (3,980 MW) must not be used as the annual peak for reserve-margin math.
- Reserve margin is sensitive to which peak is used: with dependable 4,968 MW (unverified), 4,283 MW peak -> ~16%,
  below the 18% benchmark; 3,980 MW -> ~24.8%.
- An AI report listed 3,090 MW as 2021 and 3,539 MW as 2022 peak; GRIDCo shows 3,090 = 2020, 3,246 = 2021, 3,469 = 2022.
- Its plant table sums to ~4,800 MW installed / ~4,450 MW dependable vs stated 5,818 / 4,968: ~1,000 MW unaccounted.
- EV counts conflict by definition: DVLA ~1,200 pure EVs (Oct 2025); ~17,000 incl. 2/3-wheelers; another source
  cites 2,834 BEV four-wheelers + 22,477 PHEVs (2024). Standardize categories before modelling.
- Gas: firm domestic supply ~416 mmscf/d vs power-sector need ~684 (2026) -> deficit ~268 (unverified, needs primary source).
- No known public hourly national load or plant availability data; no EV charging-load data. Requests to GRIDCo /
  Energy Commission / VRA / BPA / ECG / WAPCo are listed in the proposal doc (section 11 of the AI report's gap matrix).

## First tasks for Claude Code
1. Scaffold repo: `data/` (raw + processed), `ingest/`, `model/`, `api/`, `web/`, `tests/`. Start with SQLite or DuckDB; keep schema Postgres-compatible.
2. Load data/gridco_series.csv and data/source_register.csv into the schema with provenance columns.
3. Fetch and parse the GRIDCo 2025 Electricity Supply Plan and PURC monthly fact sheets (PDFs) into plant-level capacity
   and monthly generation tables, with page references. Flag every conflict.
4. Build the peak-demand baseline forecast and backtest it against 2019-2025 actuals and against the official forecasts.
5. Build the scenario model (available capacity and gap) and an EV module with explicit per-vehicle assumptions.
6. Only then: API, site, assistant.

## Reference
Research proposal doc (Claude Docs): https://claude.ai/artifact/GadkBhxdhyP9vhgdPd48TT
Prior art worth studying: ERCOT/ISO-NE supply-demand dashboards, Grid Status (open source), Eskom Data Portal, World Bank UPBEAT,
OSeMOSYS/TEMBA, GridWatch (nLine/CEGA Accra outage sensors), FEWS NET (early-warning credibility model),
WRI Aqueduct (water/flood open data), galamseytracker.org (satellite-based galamsey tracker by the user's friend).
