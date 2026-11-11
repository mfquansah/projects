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

## Where data lives (storage design)
Three stores, each with one job. Nothing is ever edited in place.

1. **Raw store (immutable files)**: every source document exactly as downloaded (PDFs, CSV/XLSX, later rasters).
   Local dev: `data/raw/<source_id>/<YYYY-MM-DD>_<sha256-prefix>_<filename>`. Production: S3-compatible object storage
   (Cloudflare R2, S3 or Supabase Storage). Never overwritten; a changed file is a new file. Large satellite products
   (Sentinel, CHIRPS, GPM) stay in their public archives or are stored as Cloud-Optimized GeoTIFF / Zarr and are
   *catalogued* in the DB (STAC-style), not copied into it.
2. **Structured DB (the source of truth for numbers)**: SQLite locally, Postgres in production (add PostGIS when the flood
   module starts). Use SQLAlchemy + Alembic so one schema runs on both. Hosted Postgres (Neon, Supabase or Railway) is fine.
3. **Derived/cache**: forecast outputs and scenario runs are stored in the DB with the model version and input snapshot,
   so any number shown on the site can be reproduced. Parquet exports in `data/exports/` for public download.

**Core tables** (long/tidy format so new metrics and modules need no schema change):
- `sources` (id, name, publisher, url, tier primary|secondary|ai_summary, licence, notes)
- `documents` (id, source_id, raw_path, sha256, published_date, retrieved_at, pages, parse_status)
- `entities` (id, kind national|plant|region|district|vehicle_class, name, parent_id, geometry nullable, attrs json)
- `observations` (id, metric, entity_id, period_start, period_end, period_type, value, unit, value_type actual|forecast,
  capacity_type nullable, source_id, document_id, page, table_ref, confidence high|medium|low, note, ingested_at,
  superseded_by nullable). Append-only; a correction inserts a new row and sets `superseded_by` on the old one.
- `conflicts` (id, metric, entity_id, period, observation_ids, status open|resolved, resolution_note), conflicting
  observations stay side by side; the site shows the range, never a silent average.
- `assumptions` (id, name, value, unit, rationale, source_id), every model input that is not data (growth rate, EV kWh
  per vehicle, outage rates) lives here with its reason.
- `model_runs` (id, model_version, scenario_json, inputs_snapshot, run_at) and `forecast_outputs` (run_id, metric, period,
  p10, p50, p90).
- `ingest_runs` (id, job, started_at, status, rows_added, error) and `review_queue` (values parsed from PDFs awaiting a
  human check before they are marked `confidence=high`).
- `alerts` (id, rule, triggered_at, resolved_at, payload) and `alert_rules` (metric, threshold, direction).

**Ingestion pipeline** (idempotent, re-runnable): fetch -> save raw file + hash -> record in `documents` -> parse
(PDF tables via pdfplumber/camelot, with page refs) -> write `observations` as `confidence=medium` -> push to `review_queue`
-> a human approves -> `high`. Schedule with cron or GitHub Actions: PURC monthly, GRIDCo/Energy Commission annual,
weather/satellite later. Every run logs to `ingest_runs`. A failed or empty run must alert, not fail silently.

**API**: read-only JSON endpoints over the DB (FastAPI): `/metrics`, `/observations`, `/forecast`, `/scenarios`, `/sources`,
`/alerts`. The site and the assistant both use these; nothing else touches the DB. Public CSV/Parquet download per metric.

**Hosting (start cheap)**: static site (Vercel/Netlify/Cloudflare Pages) + small API container (Fly.io/Railway/Render)
+ hosted Postgres + object storage. Nightly DB backup and a monthly restore test. Keep secrets in env vars, never in the repo.

**Licensing**: record each source's licence in `sources`. Public data stays attributed; do not republish documents whose
licence forbids it, link to them instead.

## Design (decided)
Chosen look: **"Theme 1 headline layout, forest green"** (design/MainGreen.dc.html). A story headline at the top
("Demand is growing faster than the capacity we can confirm"), then four indicator tiles, forecast chart, levers, module teasers.
- Palette: header `#1f4d36`; page `#f4f1ea`; cards `#ffffff` with `#d9d4c6` border; text `#1b2a21`; muted `#5d6358`;
  primary accent green `#2f8f5b`; "Ask the monitor" button mint `#8fdcae` with dark text `#0f2a1a`; warning amber `#8a5200`
  on `#fbefd9`; danger `#c0352b`. **No blue. No Ghana flag mark. No black header.**
- Type: Bricolage Grotesque (headings, big numbers), Public Sans (body). Radius 10px.
- Layout alternative kept for reference: design/AltPortal.dc.html (left section tabs: Overview, Demand, Capacity, Forecast,
  Scenarios, Alerts, Data and sources). Optional: add those tabs to the chosen layout once the forecast page exists.
- Screens designed so far: Home (MainGreen), Ask the monitor (design/Ask.dc.html), Flooding (design/Flood.dc.html, placeholder;
  Ask and Flood still use the earlier Theme 1 colours and need the green palette applied).
- Rules: show uncertainty (ranges, not single dates); label provisional data visibly; every figure links to its source,
  page and whether it is actual or forecast; plain-language copy; accessible contrast and keyboard-friendly controls.
- Canvas with all explorations: https://claude.ai/artifact/Ev2goae9UaNhuQkz1UbyKd
- The `.dc.html` files are design mockups, not production code. Rebuild in the chosen framework (suggested: Next.js or Astro + a
  small charting library) and keep the mockup numbers only as layout placeholders. Every number on the live site must
  come from the API.

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

## Verified so far (GRIDCo annual reports 2013-2025, via data/gridco/)
Cleaned by the data owner: one value per (year, metric), with confidence, report, PDF page, method, and the rejected values
(data/gridco/README.md, gridco_decisions.csv, build_clean.py; the raw extraction file is not in the repo yet).
- **Annual system peak (MW), 13 values, no conflicts:** 2013 1,942.9; 2014 1,970; 2015 1,933; 2016 1,997; 2017 2,192.15; 2018 2,525;
  2019 2,804; 2020 3,090; 2021 3,246; 2022 3,469; 2023 3,618; 2024 3,952; **2025 4,283**. Growth: 6.8%/yr 2013-2025, 7.3%/yr 2019-2025, 8.4% in 2025.
  2013-2016 were load-shedding years (peaks are what was delivered), 2016-2019 a rebound, steady growth since.
- Energy transmitted 2014-2023 and loss % 2013-2023 and 2025: use with confidence (loss volume / loss % cross-check settled the conflicts).
  An earlier hand-built version of 2019-2022 energy was wrong (read from blurry charts); the cleaned values replace it.
- **Use with a flag:** energy 2024 (23,692) and 2025 (25,860 GWh) are published headlines but loss volumes imply ~25,000 and ~26,900 (open conflicts);
  energy 2013 has no cross-check; 2024 loss % (3.8) is a rounded chart label.
- **Do not trend system availability** (definition changes between reports; 2024 blank). transformation_capacity is MVA of network
  equipment, NOT generation capacity.
- Still missing: generation capacity by plant, fuel mix, gas, hydro, official forecasts (need Supply Plans, PURC, Energy Commission).

## Forecast model decisions (baseline-0.2)
- Six simple models are backtested (rolling origin, same origins for all). Lowest error is the model of record: log-linear fit to all years
  (3.0% mean error, 15 overlapping tests, so a rough guide only). Fits to only the last 7 or 5 years did worse in the backtest (6.9%, 7.0%),
  partly because early test windows contained the rebound years. The 7-year fit is published as a labelled sensitivity (lower path: 5,911 MW in 2030
  vs 6,147). Revisit as years are added; do not switch models without re-running the backtest.
- Scenario growth cases are the growth that carries the 2025 peak to the baseline's p10/p50/p90 five years later (about 5.4% / 7.5% / 9.6%).
- Capacity is never defaulted in the scenario tool; EV inputs are illustrative assumptions stored with rationale.

## Data updates (decided)
Data arrives **annually** (GRIDCo, Energy Commission) and sometimes **more often** (PURC monthly, later weather/satellite). Design for that:
- Updating must be incremental and repeatable, never a manual edit of numbers in the site or database. A new data drop = new raw file
  (hash-named, never overwritten) -> parse -> rows at confidence=medium -> review -> high -> export -> site rebuild.
- A new year of an existing series is an insert. A changed value is a correction: insert the new row and supersede the old one (db/ops.py);
  never edit or delete history. Disagreeing sources go in `conflicts`, side by side.
- Every update is logged (`ingest_runs`); a failed or empty scheduled run must alert. The forecast is re-run (new `model_runs`) and the backtest
  re-checked each time new actuals arrive, and the site shows the data date and model version.
- **Built (ingest v1):** `python -m ingest.update` applies the curated CSVs to a persistent database: new rows are inserted, identical rows
  left alone, changed rows supersede the old one (history kept), rows missing from the inputs are warned about and never deleted. Every real
  run is logged in `ingest_runs` (input file hashes included); `--dry-run` previews; a failed run rolls back and exits 1; `--expect-changes`
  exits 3 if nothing new arrived; a snapshot is saved to `data/processed/backups/` before a change. `python -m ingest.raw SOURCE FILE`
  stores a source file by hash in `data/raw/<source>/` (never overwritten, read-only) and records it in `documents`.
  `scripts/refresh.sh [--build] [--expect-changes]` runs ingest -> forecast -> scenario inputs -> site data -> site build.
  `python -m ingest.load` is the dev shortcut (delete the DB, apply to an empty one: same code path).
- **To add a new year or month of an existing series:** add the row(s) to the curated CSV (and the source to `data/source_register.csv`), run
  `python -m ingest.update --dry-run`, read the plan, then `scripts/refresh.sh`, review the diff of `web/src/data/energy.json`, commit.
- **Not needed:** PDF parsing. Data comes as curated CSV; `ingest.raw` only files a source document by hash if a copy is wanted.
- **Not built yet:** alerts beyond the exit code; automated schedule; export/site support for plant-level capacity (the loader accepts it already).
- **Open decision, where the persistent database lives for scheduled runs.** A GitHub Actions job starts with an empty disk, so either
  (A) hosted Postgres is the store of record (`DATABASE_URL` is already honoured; migrations are SQLite-tested only, so test them on Postgres first), or
  (B) the committed curated CSVs stay the record and the database is rebuilt each run (simple, but superseded history lives only in git).
  Until one is chosen, run updates locally and commit the CSVs and `energy.json`.

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
1. Scaffold repo: `data/` (raw + processed), `ingest/`, `model/`, `api/`, `web/`, `tests/`, `design/`. Create the schema above with Alembic (SQLite locally, Postgres-compatible).
2. Load data/gridco_series.csv and data/source_register.csv into the schema with provenance columns.
3. Supply-side data arrives as curated CSV (the data owner extracts it from the source documents; we do not parse PDFs). Drop files in
   `data/observations/` using the layout in `data/templates/` (plant capacity installed vs dependable, monthly generation, official forecasts),
   run `python -m ingest.update`. Disagreeing sources are stored side by side and flagged automatically.
4. Build the peak-demand baseline forecast and backtest it against 2019-2025 actuals and against the official forecasts.
5. Build the scenario model (available capacity and gap) and an EV module with explicit per-vehicle assumptions.
6. Only then: API, site, assistant.

## Reference
Research proposal doc (Claude Docs): https://claude.ai/artifact/GadkBhxdhyP9vhgdPd48TT
Prior art worth studying: ERCOT/ISO-NE supply-demand dashboards, Grid Status (open source), Eskom Data Portal, World Bank UPBEAT,
OSeMOSYS/TEMBA, GridWatch (nLine/CEGA Accra outage sensors), FEWS NET (early-warning credibility model),
WRI Aqueduct (water/flood open data), galamseytracker.org (satellite-based galamsey tracker by the user's friend).
