"""Build a clean, publishable copy of the project in `public-release/`.

    python tools/make_public.py

It copies the tracked files, leaves out the private ones (blog drafts, progress reports, the build-trail page renderer),
rewrites the lines that mention the author's real recordings or accounts, adds the licence, a newcomer README and
contribution notes, then SCANS the result and refuses to finish if anything personal is left. Re-run it any time;
it starts from scratch each time. The real project folder is never changed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public-release"

# Left out of the public copy entirely.
EXCLUDE = (
    "docs/blog-notes.md", "docs/blog-draft.md", "docs/progress/", "docs/.build-trail-state",
    "docs/public-release-review.md", "tools/render_trail.py", "tools/trail_template.html", "public-release/",
)

# (file, old text, new text). Every one MUST match, so a changed source line is noticed instead of silently leaking.
REWRITES: list[tuple[str, str, str]] = [
    ("docs/brief.md", "in use on the user's real library; bulk import under way) | Link: voice-library/ in mfquansah/projects",
     "in use on the author's own library; bulk import under way)"),
    ("docs/decisions.md", "Python pipeline in `voice-library/` in mfquansah/projects, matching ghana-resource-monitor conventions.",
     "Python pipeline in `voice-library/`, matching the conventions of the author's other Python project."),
    ("docs/decisions.md", "we can add Good evening, Michael .. like my name.", "we can add Good evening, <name> .. like my name."),
    ("docs/decisions.md", "the one note the user could check (Weija Gbawe) matched.", "the one note the author could check by hand matched."),
    ("docs/revisit.md", "(HR coaching notes appeared for \"baby making cute sounds\")", "(unrelated work notes appeared for \"baby making cute sounds\")"),
    ("docs/revisit.md", "only \"Weija Gbawe\" was checked by hand. The note `5:16:25, 2:50 PM.m4a` is dated 2020-01-14, which doesn't fit its name.",
     "only one recording was checked by hand. One note is dated 2020, which doesn't fit its name."),
    ("docs/revisit.md", "`Red Fox Rd 10/11/12` (baby babbling, failed laugh, laugh)", "a few test recordings (baby babbling, a failed laugh, a laugh)"),
    ("docs/manual.md", "`--name Michael`", "`--name Ama`"), ("docs/manual.md", "\"Good evening, Michael\"", "\"Good evening, Ama\""),
    ("web/manual.html", "--name Michael", "--name Ama"),
    ("vl/cli.py", "e.g. --name Michael", "e.g. --name Ama"),
    ("tests/test_profile.py", "Michael", "Ama"),
    ("questions.example.json", "the one-on-one about dashboard scope", "the team meeting about the roadmap"),
    ("questions.example.json", "that thing I recorded at Weija Gbawe", "that thing I recorded at the lake"),
    ("questions.example.json", "\"Weija Gbawe.m4a\"", "\"Lake walk.m4a\""),
    ("questions.example.json", "New Recording 197.m4a", "Team meeting.m4a"),
    ("questions.example.json", "New Recording 250.m4a", "Voice note 1.m4a"),
    ("questions.example.json", "New Recording 251.m4a", "Voice note 2.m4a"),
    ("vl/eval.py", "New Recording 197.m4a", "Team meeting.m4a"),
]

# Words that must not appear anywhere in the public copy (except in LICENSE and BRAND.md, which name the author).
FORBIDDEN = [r"Weija", r"Gbawe", r"Red Fox", r"mfquansah", r"Quansah", r"Michael", r"ghana", r"HR coaching",
             r"sk-ant-", r"@gmail", r"michaelq", r"Hope St"]
ALLOWED_FILES = {"LICENSE", "BRAND.md"}

LICENSE = """MIT License

Copyright (c) 2026 Michael Quansah

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

BRAND = """# Name and logo

The **code** in this repository is released under the MIT licence (see `LICENSE`).

The **name "Kasa Adaka"** and the **logo** (the outlined tile with four coloured bars, and the lettering) belong to the
author and are **not** covered by the MIT licence. You are welcome to fork the code, change it and share your version.
If you do, please give your version its own name and its own logo, so people don't mistake it for the original.

Where to change them:

- the name appears in `web/index.html`, `web/js/app.js`, `web/manual.html`, `vl/api/main.py`, `vl/cli.py` and the docs
  (try `grep -ri "kasa adaka" .`);
- the logo is the `LOGO_SVG` block in `web/js/app.js` and the tab icon in `web/index.html`.

The fonts in `web/fonts/` are open-licence fonts with their own licence files next to them.

This note is a plain-language statement of intent, not legal advice.
"""

CONTRIBUTING = """# Contributing

Thanks for wanting to help. This is a small personal project, so keep changes small and easy to review.

## Set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                      # the tests use stand-ins for Whisper, Claude and the models; no downloads or keys needed
python tools/demo_server.py    # a made-up library to click around in (no recordings, no key)
```

## Privacy rules (please read)

This app is built for private audio. When you open an issue or a pull request:

- **Never attach or paste real recordings, transcripts, titles, summaries or screenshots of your own library.** Use the demo
  library (`tools/demo_server.py`) or invented text.
- **Never paste an API key.** If one leaks, delete it in your provider's console and make a new one.
- Don't add code that sends **audio** anywhere. The design rule is that audio stays on the user's computer and only text
  goes to the language model.

## Good first ideas

See "Wish list" in the README. Making transcription faster, a settings screen, a share/export button, and better
sound-detection thresholds are all welcome.

## Before you open a pull request

- `pytest -q` passes, and new behaviour has a test.
- If you changed the page, run `node tools/e2e.js` (needs `npm i playwright`): it drives every screen in a real browser.
- Describe what you changed and why, in plain language.
"""

README = """# Kasa Adaka

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

Share a single recording; a family library where several people load their voice notes and share them; a phone app;
faster transcription; a settings screen. Ideas and pull requests are welcome (see `CONTRIBUTING.md`).

## Licence and name

The code is MIT licensed (`LICENSE`). The name "Kasa Adaka" and its logo are not part of that licence; if you fork the
project please give it your own name and logo (`BRAND.md`).
"""


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def excluded(rel: str) -> bool:
    return any(rel == e or (e.endswith("/") and rel.startswith(e)) for e in EXCLUDE)


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    copied = []
    for rel in tracked_files():
        if excluded(rel) or rel == "README.md":
            continue
        dest = OUT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest)
        copied.append(rel)
    problems = []
    for rel, old, new in REWRITES:
        f = OUT / rel
        if not f.is_file():
            problems.append(f"missing file for rewrite: {rel}")
            continue
        text = f.read_text()
        if old not in text:
            problems.append(f"text to rewrite not found in {rel}: {old[:60]!r}")
            continue
        f.write_text(text.replace(old, new))
    (OUT / "LICENSE").write_text(LICENSE)
    (OUT / "BRAND.md").write_text(BRAND)
    (OUT / "CONTRIBUTING.md").write_text(CONTRIBUTING)
    (OUT / "README.md").write_text(README)
    # the final safety net: nothing personal may remain
    pat = re.compile("|".join(FORBIDDEN), re.IGNORECASE)
    for f in sorted(OUT.rglob("*")):
        if not f.is_file() or f.name in ALLOWED_FILES or f.suffix in (".woff2", ".png", ".pyc"):
            continue
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            m = pat.search(line)
            if m:
                problems.append(f"{f.relative_to(OUT)}:{n}: found {m.group(0)!r}")
    if problems:
        print("NOT READY. Fix these first:")
        print("\n".join("  " + p for p in problems))
        return 1
    print(f"Built {OUT.relative_to(ROOT)}/ with {len(list(OUT.rglob('*')))} entries; scan found nothing personal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
