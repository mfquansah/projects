# Kasa Adaka

*Kasa adaka* is Twi for "talk box". It is a **searchable library for your voice memos**: it listens to each recording on your
own computer, writes a transcript, gives it a title and a summary, sorts it into collections, notices sounds like a baby
laughing, and lets you find things by asking in plain language, the way you search photos.

> Search "the recording of my baby singing last week" and get the clip, with a one-line reason why it matched.

It started because Apple Photos can search your pictures by what's in them, and nothing does that for audio.

## How it works

Everything is built once, when a recording is imported, and then search reads what was built:

1. **Transcribe** the speech with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), on your computer.
2. **Title, summarise and sort** the transcript with Claude (text only).
3. **Index** it two ways: exact words (SQLite full-text search) and meaning (a small embedding model).
4. **Listen for sounds** (baby laugh, cry, babble) with an audio classifier trained on AudioSet, on your computer.
5. **Search**: a question is turned into filters (topic, dates, "my longest note"), run against the index, and the top
   results are labelled match / partial / related with a reason.

Stack: Python, SQLite (FTS5), FastAPI, plain JavaScript (no build step), faster-whisper, sentence-transformers, a Hugging
Face audio classifier, and the Claude API.

## Privacy

- **Audio never leaves your computer.** Transcription and sound detection run locally.
- **Only text goes to Claude**: transcripts (to write titles and summaries) and your search questions with short snippets.
  You need your own Anthropic API key; the app never ships with one.
- The page listens only on `127.0.0.1` (your own computer) and has no login. Don't expose it to a network.
- Your library lives in `~/VoiceLibrary` (outside this repository). Deleting a recording in the app removes the app's copy
  only; your originals are never touched.

## Try it without any recordings

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python tools/demo_server.py        # a made-up library with fake models; then open http://127.0.0.1:8798
```

## Run it on your own recordings (macOS)

```bash
export ANTHROPIC_API_KEY=...       # your own key; for example: read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
python -m vl.cli serve --open --name YourName
```

Then use the **Import** page: it can read the Mac's Voice Memos library directly (macOS asks you to give Terminal
*Full Disk Access*; the page explains how). Recordings over 45 minutes are skipped by default (`--max-minutes`).
Everyday commands are on a one-page manual inside the app (the **Manual** link in the sidebar) and in `docs/manual.md`.

Notes: developed on a Mac with Python 3.12 (also runs on 3.13). The first import downloads the speech and sound models
(several hundred MB). Transcription is the slow part, roughly 9 seconds of work per minute of audio on a laptop CPU.

## Tests

```bash
pytest -q
```

## What's here

- `vl/` the library: import, transcription, enrichment, search, sound detection, API
- `web/` the page (plain HTML, CSS and JavaScript; fonts are bundled, nothing loads from the internet)
- `tests/` unit tests with stand-ins for the heavy models; `tools/` a demo server and a browser test
- `docs/` the build trail: the product brief, the decision log (what we chose, what we rejected and why), a list of
  guesses and unverified things (`revisit.md`), and a shelf of features chosen for later (`build-later.md`)

## Wish list

A family library where several people load their voice notes and share them; a phone app; faster transcription; a
settings screen; a share link that needs no email app. (Sharing one recording by email draft or download already works.) Ideas and pull requests are welcome (see `CONTRIBUTING.md`).

## Licence and name

The code is MIT licensed (`LICENSE`). The name "Kasa Adaka" and its logo are not part of that licence; if you fork the
project please give it your own name and logo (`BRAND.md`).
