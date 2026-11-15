# Voice Note Library

Searchable library for personal voice notes: transcribes each note locally, adds a title, summary, category and tags,
and finds notes by keyword, meaning, date or category. See `docs/brief.md` for the product and `docs/decisions.md` for why.

**Status: milestone 1 (speech pilot, command line).** Tested with fakes only. It has not yet been run on real recordings.

## Run the pilot on your Mac
```bash
cd voice-library
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # only transcript text is sent; audio never leaves your Mac
```
1. In Voice Memos, select 20-30 recordings and drag them into a folder, e.g. `~/Desktop/pilot`.
2. Import, then process:
```bash
python -m vl.cli import ~/Desktop/pilot --limit 25
python -m vl.cli process
python -m vl.cli status
python -m vl.cli search "that idea about the app name"
python -m vl.cli search "baby" --category "Family memories" --since 2026-01-01
```
Data lives in `~/VoiceLibrary` (override with `VL_HOME`). Originals are copied, never modified. Re-running any command only does new work.

## Check during the pilot
- `status` shows failures per note and the reason.
- Do imported dates look right? (macOS birth time is used first; `date_source` in the DB says which source was used. Not yet verified for Voice Memos exports.)
- Does a natural-language search return the note you meant? Write down misses; they decide what to fix next.

## Tests
```bash
pytest -q
```

## Not built yet
Sound tagging (baby laughing/crying, milestone 2), LLM natural-language query parsing, web page, reading Apple's library directly, Alembic migrations.
