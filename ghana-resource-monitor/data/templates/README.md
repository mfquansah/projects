# Observation file template

Copy `observations_template.csv` to `data/observations/<something>.csv` (one file per source or topic), fill it in, then:

```bash
.venv/bin/python -m ingest.update --dry-run   # read the plan
.venv/bin/python -m ingest.update             # apply it
```

One row = one number. A blank value is a gap: leave the row out. Anything invalid stops the whole load and names the file and line.

| column | meaning |
|---|---|
| `entity_kind` | `national`, `plant`, `region`, `district` or `vehicle_class` |
| `entity_name` | e.g. `Ghana`, or the plant's name (spell it the same way every time) |
| `parent_name` | optional; blank means Ghana. Use it for a plant inside a region, etc. |
| `fuel` | optional, plants only: `hydro`, `gas`, `diesel`, `solar` ... |
| `metric` | what is measured, e.g. `generation_capacity`, `generation` |
| `period_type` | `annual` or `monthly` (never mix them in one row) |
| `year`, `month` | `month` 1-12 for monthly rows, blank for annual rows |
| `value`, `unit` | number and its unit (`MW`, `GWh`, ...) |
| `value_type` | `actual` or `forecast`. A forecast is never an actual |
| `capacity_type` | `installed`, `dependable`, `available` or `peak_coincident`; blank if not a capacity |
| `source_id` | must exist in `data/source_register.csv` (S13, the AI report, is refused) |
| `page` | required: where in the source the number is |
| `table_ref` | optional: table or figure name |
| `confidence` | `high`, `medium` or `low` |
| `note` | how you read it, caveats, scope |

## Rules the loader enforces
- Different sources giving different values for the same fact are both kept and flagged as a conflict. Nothing is averaged.
  If you decide one is right, say so in `note` and keep both rows.
- Re-running is safe. A changed value replaces the old one and the old one stays in history.
- Never use a monthly peak as an annual peak, and never record a forecast as an actual.
- Installed and dependable capacity are separate rows (same plant, same year, different `capacity_type`). Network equipment
  (transformers, lines) is not generation capacity.

## Example rows (illustrative layout only, not data)
```
plant,Example Plant,,gas,generation_capacity,annual,2025,,100,MW,actual,installed,S02,12,Table 3,medium,nameplate
plant,Example Plant,,gas,generation_capacity,annual,2025,,90,MW,actual,dependable,S02,12,Table 3,medium,
```
