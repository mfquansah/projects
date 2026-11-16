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

## The web page
```bash
export ANTHROPIC_API_KEY=...         # Claude writes titles/summaries and understands questions
python -m vl.cli serve --open        # then use http://127.0.0.1:8765
```
One big search box. Typing shows instant results from your own computer; pressing Enter asks the full question (dates, "my longest",
baby sounds), with Claude's one-line verdict and a Match / Partly / Related label on each result. Screens:
- **Library**: search, example searches drawn from your own notes, recent recordings, and your collections down the left.
- **Recording**: player with a waveform and markers where sounds were heard, a timestamped transcript (click a line to jump there, find within it),
  editable title, summary and tags, details (including where the recording date came from), and related recordings.
- **Import**: three ways in. (1) **Import from Voice Memos**: the app reads the Mac's Voice Memos library directly (macOS may ask you to give Terminal
  *Full Disk Access*; the page tells you exactly how). (2) **Import a folder by path**: read in place. (3) Drop audio files or a folder onto the page.
  Files read in place are never changed or deleted. Each file is transcribed, titled, sorted, indexed and checked for sounds, one at a time, with
  live progress. A bad file shows its error and never stops the others. Anything already imported is skipped.
  **Automatic sync** (Import screen, off by default): checks Voice Memos every 10 minutes and imports new recordings; the sidebar shows
  "Synced 3 min ago · 2 new" with Sync now. Turning it on asks first, because the first sync imports the whole library (hours for ~1,000 notes).
  It is one-way and read-only, remembers what it has seen, retries failures a few times, and reports (never re-imports) recordings you trimmed after import.
  It runs while `vl serve` runs; starting at login isn't built yet.
  **Dragging straight out of the Voice Memos app does not work in a browser** (it hands over file promises, not files); the page says so.
- **Needs attention**: Claude's suggested collections (Accept / Dismiss), recordings that may be accidental (Keep / Archive), tags you can turn
  into collections, and Archived (Restore). **Archive only hides a recording; nothing is ever deleted.**

Claude is part of the app, not an option. Without `ANTHROPIC_API_KEY` the page says so, searches are basic, and importing explains what's missing.
Audio and transcription never leave your computer; transcript text and your questions go to Claude. The page listens on 127.0.0.1 only, checks the
Host header, and refuses to serve any file outside `~/VoiceLibrary/audio`. Phone access is planned but not built (it needs login first).
No fonts or scripts are loaded from the internet.

Developer tools: `python tools/demo_server.py` serves a made-up library with fake Claude/Whisper, and `node tools/e2e.js` (needs `npm i playwright`)
drives every screen in a real browser, including upload, and fails on console errors or stray "null"/"undefined" text.

## How sure is it?
After `ask` finds candidates, Claude reads them and labels each `<MATCH>` (it's what you described), `<partial>` (covers part of it) or `<related>`
(same area), then the output starts with a line like `Result: One clear match.` / `2 likely matches.` / `No clear match; these only partly match.`
Strongest labels come first, and results Claude didn't endorse are dropped. The labels are Claude's judgement, so treat them as a strong hint,
not proof; read the `why:` line. Sound and sorted answers (longest, newest) have no labels: they're ordered by confidence or by the data.

## Sound detection (baby laughing, crying, babbling)
```bash
python -m vl.cli sounds --limit 3      # try 3 notes first: the first run downloads the model, and long notes are slow
python -m vl.cli sounds                # then the rest (resumable: skips notes already checked)
python -m vl.cli sounds --redo         # re-check everything (needed once after upgrading to the new 0.10 storage threshold)
python -m vl.cli ask "the recording of my baby laughing"
```
A model trained on AudioSet listens to each note in 10-second windows, locally (audio never leaves your Mac), and stores baby cry, laughter,
giggle and babbling sounds down to 0.10 confidence. Searches then decide what counts: 0.30 and up is "heard", 0.15 to 0.30 is shown as
"possibly" and ranked below the confident ones, below 0.15 is ignored. So a faint baby giggle can still surface instead of vanishing. `ask` then finds notes by sound even when nobody speaks, ranks them by confidence,
and shows where in the note it heard it (`sound: baby_laugh 0.82 at 1:10`).
**Not yet verified on real audio:** speed (long notes may take minutes each on CPU; try `--device mps`), the cutoffs (`--threshold` and
`MIN_SOUND_CONFIDENCE`, both 0.3, are guesses), and the model's label names (matched by keyword, and it stops with a clear message
if it can't find baby cry/laugh labels). Adult laughter can be mistaken for baby laughter.

## Ordering questions
`ask` understands "my longest note", "my 3 newest", "the shortest note about the dashboard". Notes are matched on topic first, then ordered.
Lengths come from the audio file when known, otherwise from the end of the last transcribed speech (approximate), and notes with neither are
left out and reported.

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
