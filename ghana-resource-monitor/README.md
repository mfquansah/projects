# Ghana Resource Monitor

See `CLAUDE.md` for the project brief, data rules and known discrepancies, and `design/` for the mockups.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m ingest.load                      # dev: delete and rebuild data/processed/monitor.sqlite from the CSVs
.venv/bin/python -m ingest.update --dry-run          # preview an incremental update of the persistent DB
.venv/bin/python -m ingest.update                    # apply it (logged; snapshot first; history never rewritten)
.venv/bin/python -m ingest.raw S02 path/to/file.pdf  # store a source document by hash in data/raw/
scripts/refresh.sh --build                           # ingest -> forecast -> scenario inputs -> site data -> site build
.venv/bin/python -m model.baseline                   # peak-demand baseline forecast + backtest (stores a model run)
.venv/bin/python -m model.scenario                   # seed scenario/EV assumptions (with rationale) into the DB
.venv/bin/python -m unittest discover -s tests -t .  # tests
.venv/bin/alembic revision --autogenerate -m "..."   # after editing db/models.py
```

Layout: `data/` curated CSVs + raw files, `db/` models and write helpers, `migrations/` Alembic, `ingest/` loaders,
`model/` forecasts, `api/`, `web/` (static site first, Vercel), `design/` mockups, `tests/`.

Status: Phase 0 dataset v0 loaded; Phase 1 baseline forecast done. Scenario model is blocked on verified plant
capacity (GRIDCo Supply Plan / PURC fact sheets not yet obtained).

## Site (web/)
Static Astro site; every number comes from `web/src/data/energy.json`, generated from the database.
```bash
.venv/bin/python -m ingest.load && .venv/bin/python -m model.baseline && .venv/bin/python -m model.scenario && .venv/bin/python -m ingest.export
cd web && npm install && npm run dev      # or: npm run build; npm test checks the JS scenario math against Python
```
Deploy to Vercel with **Root Directory = `web`** (framework: Astro). `energy.json` is committed so Vercel needs no Python;
re-run the four commands above and commit when the data changes.

## Scenario model
`model/scenario.py` (Python) and `web/src/lib/scenario.js` (browser) implement the same arithmetic; `tests/vectors/scenario.json`
is checked by both test suites. Capacity is always a user input until verified from primary documents. EV figures
are illustrative assumptions stored in the `assumptions` table with their rationale.
