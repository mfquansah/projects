# Kasa Adaka: pocket manual

The commands you'll use, in the order you'll need them. Everything runs in **Terminal on your Mac**.
Anything in a grey code box can be pasted as it is.

---

## 1. Start the app (every time you open a new Terminal)

**Step 1.** Go to the project and switch on its Python environment:
```bash
cd ~/Desktop/projects/voice-library && source .venv/bin/activate
```

**Step 2.** Set your Claude key for this window. Paste the key when the cursor waits and press Enter. Nothing shows on screen, which is normal:
```bash
read -s ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
```

**Step 3.** Start the app and open it in your browser:
```bash
python -m vl.cli serve --open
```

Leave this Terminal window open while you use the app. Closing it stops the app.
The page lives at http://127.0.0.1:8765

> Never paste your API key into chat, a document or a screenshot. If it ever leaks, delete it in the Anthropic Console (API keys) and make a new one.

---

## 2. Stop the app

In the Terminal window where it's running, press **Ctrl+C**.

This stops everything, including search, until you start it again. Recordings already finished are saved.

---

## 3. Update to the newest version

Stop the app (Ctrl+C), then:
```bash
git pull
```
Start it again (section 1, step 3), then in the browser press **Cmd+Shift+R** to clear the old page.

If you get `ModuleNotFoundError` after a pull, install what's new and try again:
```bash
pip install -r requirements.txt
```

---

## 4. Importing

**On the page:** Import, then **Import from Voice Memos**:
- *Try a test batch (25 newest)*: your newest 25 that aren't in the library yet, with a timing report.
- *Import the next 100*: the next 100 newest. Good for working through the library in chunks.
- *Import all*: everything, newest first.

**Pause:** there's no pause button yet. To stop safely, press **Ctrl+C**, then restart the app and click the same button again. It skips what's already done and picks up what wasn't finished. The recording being worked on starts its current step again.

**Limit by length.** Recordings longer than **45 minutes** are skipped (usually meetings), before anything is copied, transcribed or sent to Claude. Change it when you start the app:

| You want | Start the app with |
|---|---|
| Skip over 45 min (the default) | `python -m vl.cli serve --open` |
| Skip over 60 min | `python -m vl.cli serve --open --max-minutes 60` |
| Skip over 20 min | `python -m vl.cli serve --open --max-minutes 20` |
| No limit | `python -m vl.cli serve --open --max-minutes 0` |

The limit applies to Voice Memos, folder imports and sync. Dragging files onto the page isn't limited.
After you change it, recordings that were skipped before get imported the next time you import.

---

## 5. Other start-up settings

Add these to the `serve` command:

| Setting | What it does |
|---|---|
| `--max-minutes N` | skip recordings longer than N minutes (0 = no limit) |
| `--port 8766` | use a different page address, if 8765 is busy |
| `--whisper-model base` | a smaller, faster transcription model (less accurate); the default is `small` |
| `--llm-model NAME` | which Claude model writes titles and answers; the default is `claude-haiku-5-5` |
| `--name Michael` | the name in the greeting ("Good evening, Michael"). Saved after the first time, so you don't repeat it. `--name ""` removes it |

Example, a faster and looser setup:
```bash
python -m vl.cli serve --open --whisper-model base --max-minutes 30
```

Set once per Terminal window, before `serve`:
```bash
export VL_HOME=/Volumes/MyDrive/KasaAdaka       # keep the library on another drive
export VL_PRICE_IN_PER_MTOK=1.00                # your Claude prices in dollars per million tokens;
export VL_PRICE_OUT_PER_MTOK=5.00               #   then the results card can show a dollar estimate
```
(The prices above are placeholders: put in the real ones from Anthropic's pricing page.)

---

## 6. Sounds (baby laughing, crying, babbling)

```bash
python -m vl.cli sounds --limit 3        # try 3 recordings first; it can be slow
python -m vl.cli sounds                  # check all the recordings not yet checked
python -m vl.cli sounds --redo           # re-check everything (after changing the threshold)
python -m vl.cli sounds --inspect "/path/to/file.m4a"   # show what the model hears in one file
```

| Option | Meaning |
|---|---|
| `--threshold 0.10` | the lowest confidence to store (default 0.10). Searches decide what counts: 0.30 and up is "heard", 0.15 to 0.30 is "possibly" |
| `--device mps` | try the Mac's graphics chip; may be faster (untested) |

---

## 7. How long does each step take? (the timing tool)

Runs a few recordings through every step in a throwaway library. Your real library isn't touched.
```bash
python -m vl.cli profile --voicememos 3
```

| Option | Meaning |
|---|---|
| `--voicememos N` | use the N newest Voice Memos |
| `--no-sounds` | skip sound detection |
| `--no-claude` | skip the Claude step (no key needed) |
| `--whisper-model base` | time a different transcription model |

---

## 8. Search from the terminal (without the page)

```bash
python -m vl.cli ask "the recording of my baby laughing"
python -m vl.cli search "app name" --since 2026-11-01
python -m vl.cli search "baby" --keyword-only      # exact words only, no downloads
python -m vl.cli status                            # counts, plus any recordings that failed and why
```

---

## 9. Look at your data

```bash
du -sh ~/VoiceLibrary                              # how much space the library uses
sqlite3 ~/VoiceLibrary/library.db ".tables"        # the tables
sqlite3 ~/VoiceLibrary/library.db "select id, original_name, recorded_at from notes limit 5;"
```

Where things live (`~/VoiceLibrary`):
- `library.db`: the database (transcripts, titles, summaries, collections, sounds, search indexes)
- `audio/`: a copy of every imported recording. Your originals in Voice Memos are never changed
- `cache/`: waveform pictures (rebuilt automatically)

Back it up with Time Machine, or copy the folder.

---

## 10. When something goes wrong

| What you see | What to do |
|---|---|
| `command not found: python` or `No module named vl` | Run step 1 again (`source .venv/bin/activate`) |
| `ModuleNotFoundError` after `git pull` | `pip install -r requirements.txt` |
| The page says Claude isn't connected | Set the key (section 1, step 2) in the same window, then start the app again |
| Import says macOS is blocking Voice Memos | System Settings, Privacy & Security, Full Disk Access, turn on Terminal, then **fully quit** Terminal (Cmd+Q) and reopen it |
| The page looks old after an update | Hard refresh: **Cmd+Shift+R** |
| `Address already in use` | The app is already running in another window (close it), or add `--port 8766` |
| One recording failed to import | `python -m vl.cli status` shows which and why; the others keep going |
| A search can't find something you know is there | Try different words, or check the recording was imported (Import page, or `status`) |

---

## 11. What's built and what isn't (so nothing surprises you)

- **Share by email…** (recording page) opens a Mail draft with the audio attached and an optional message; you review it in Mail and press Send, so nothing is sent from the app. The first time, macOS asks whether Terminal may control Mail: say yes (Privacy & Security, Automation). **Download audio** is its own button just below, and saves the file under a readable name (use it for Gmail).
- **Archive** hides a recording and can be undone (Needs attention, then Archived).
- **Delete permanently** (recording page, below Archive) erases the app's data and its copy of the audio, **can't be undone**, and the recording is skipped by later imports. Your original in Voice Memos is never touched; delete it there yourself if you want it gone. One recording at a time.
- **No pause button** for imports yet (use Ctrl+C and restart, section 4).
- **Sync** (automatic import of new recordings) is built but switched off on the page, and it only runs while the app is open.
- **Sorting** collection lists is newest first only. In search, ask in words: "my longest note about work".
- Audio never leaves your Mac. Only transcript text and your search questions go to Claude.
