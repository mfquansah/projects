#!/usr/bin/env bash
# One-command data refresh: ingest -> forecast -> scenario inputs -> site data -> (optionally) build the site.
# Usage: scripts/refresh.sh [--build] [--expect-changes]
# Exits non-zero if any step fails, or (with --expect-changes) if the ingest found nothing new, so a scheduled
# run cannot fail silently.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
BUILD=0; EXPECT=""
for a in "$@"; do case "$a" in --build) BUILD=1;; --expect-changes) EXPECT="--expect-changes";; esac; done

$PY -m ingest.update $EXPECT
$PY -m model.baseline --no-print >/dev/null
$PY -m model.scenario
$PY -m ingest.export
if [ "$BUILD" = 1 ]; then (cd web && npm ci --silent && npm run build); fi
echo "refresh complete"
