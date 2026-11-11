# Ghana Resource Monitor

See `CLAUDE.md` for the project brief, data rules and known discrepancies, and `design/` for the mockups.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m ingest.load                      # build data/processed/monitor.sqlite (Alembic migrations + CSVs)
.venv/bin/python -m model.baseline                   # peak-demand baseline forecast + backtest (stores a model run)
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
.venv/bin/python -m ingest.load && .venv/bin/python -m model.baseline && .venv/bin/python -m ingest.export
cd web && npm install && npm run dev      # or: npm run build
```
Deploy to Vercel with **Root Directory = `web`** (framework: Astro). `energy.json` is committed so Vercel needs no Python;
re-run the three commands above and commit when the data changes.
