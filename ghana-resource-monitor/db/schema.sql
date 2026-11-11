-- Ghana Resource Monitor schema. Portable SQL (SQLite now, Postgres later):
-- no vendor-specific types; CHECK constraints enforce the data rules in CLAUDE.md.

CREATE TABLE IF NOT EXISTS sources (
    source_id    TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    publisher    TEXT,
    date         TEXT,
    url          TEXT,
    status       TEXT NOT NULL,
    contains     TEXT,
    reliability  TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id         INTEGER PRIMARY KEY,
    metric         TEXT NOT NULL,
    year           INTEGER NOT NULL,
    month          INTEGER CHECK (month BETWEEN 1 AND 12),
    value          REAL NOT NULL,
    unit           TEXT NOT NULL,
    period_type    TEXT NOT NULL CHECK (period_type IN ('annual','monthly','hourly')),
    value_type     TEXT NOT NULL CHECK (value_type IN ('actual','forecast')),
    capacity_type  TEXT CHECK (capacity_type IN ('installed','dependable','available','peak_coincident')),
    source_id      TEXT NOT NULL REFERENCES sources(source_id),
    pdf_page       TEXT,
    confidence     TEXT NOT NULL,
    note           TEXT,
    -- A monthly row must say which month; an annual row must not.
    CHECK ((period_type = 'monthly' AND month IS NOT NULL)
        OR (period_type <> 'monthly' AND month IS NULL))
);

-- Never store the same fact twice from the same source; conflicts from
-- different sources are kept side by side (different source_id).
-- COALESCE because NULLs never collide in a plain UNIQUE constraint.
CREATE UNIQUE INDEX IF NOT EXISTS uq_obs_fact ON observations
    (metric, year, COALESCE(month, 0), period_type, value_type, source_id);

CREATE INDEX IF NOT EXISTS idx_obs_metric_year ON observations (metric, year);
