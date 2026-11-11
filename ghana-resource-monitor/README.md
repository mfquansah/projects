# Ghana Resource Monitor

See `CLAUDE.md` for the project brief, data rules and known discrepancies.

```bash
python3 -m ingest.load                      # rebuild data/processed/monitor.sqlite from data/*.csv
python3 -m unittest discover -s tests -t .  # run tests (stdlib only, no installs)
```

Status: Phase 0 (verified dataset v0). Layout: `data/` curated CSVs + raw files, `db/` schema,
`ingest/` loaders, `model/` forecasts, `api/`, `web/`, `tests/`.
