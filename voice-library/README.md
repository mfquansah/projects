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
python -m vl.cli ask "the recording of my baby laughing about two weeks ago"
python -m vl.cli search "baby" --category "Family memories" --since 2026-01-01
```
Data lives in `~/VoiceLibrary` (override with `VL_HOME`). Originals are copied, never modified. Re-running any command only does new work.

## Asking in plain language
`ask` uses Claude to turn a question into filters (what it's about, likely spoken words, category, date range), runs the same
search, then asks Claude to rerank the top results with a one-line reason. If the LLM fails, it falls back to plain search and
says so; if a filter finds nothing it relaxes the category, then the dates, and tells you. Only the question and short transcript
snippets are sent; audio never is. Add `--no-rerank` to skip the second call.

## Check during the pilot
- Is the meaning-search cutoff right? (`MIN_SIMILARITY` in `vl/index/search.py` is a guess: too high misses notes, too low returns unrelated ones.)
- `status` shows failures per note and the reason.
- Do imported dates look right? (macOS birth time is used first; `date_source` in the DB says which source was used. Not yet verified for Voice Memos exports.)
- Does a natural-language search return the note you meant? Write down misses; they decide what to fix next.

## Eval: scoring search quality
**Don't remember your notes? Generate the questions from them:**
```bash
python -m vl.cli evalgen --out questions.json
```
Claude writes questions per note (answer = that note), the library's own data gives "longest / newest / busiest month" answers,
and "nothing should match" topics are kept only if absent from every transcript. You then review each content question next to the
note it came from (Enter = keep, n = drop, or type a better one): recognising a match is easier than remembering one.
Caveat: questions written from a transcript echo its wording, so scores run optimistic; treat this as a smoke test.
The property questions (longest, newest) are expected to fail until sorting is built.

**Or write your own:** copy `questions.example.json` to `questions.json` and replace it with 10-15 questions. Each says which note(s) should come
back, by exact filename (see `status`). Use kind `none` for a topic you never recorded; the right answer is "nothing".
```bash
python -m vl.cli eval questions.json
```
It runs every question through `search` (local), `ask-norerank` and `ask`, and prints hit@1/3/5, MRR (how high the right note ranks),
how often "nothing" was correctly returned, seconds, and LLM call counts, plus every miss. Full results are saved as JSON, so you can
compare runs after a change. Misspelled filenames in the file stop the run instead of silently scoring as misses.
Use `--modes search` for a free local-only run. Call counts are a proxy for cost; token usage isn't measured yet.
The example file's filenames are placeholders: it only works on a library that has those notes.

## Tests
```bash
pytest -q
```

## Not built yet
Sound tagging (baby laughing/crying, milestone 2; `ask` already recognizes a sound in the question but says it can't apply it yet), web page, reading Apple's library directly, Alembic migrations.
