# Revisit list

Things we deliberately deferred, guessed at, or never verified. Each says what to check and where it lives. Updated 2026-11-16.
Status: `open` unless noted. Tick items off (and add a decision-log entry) when resolved.

## A. Guessed values to tune on real recordings
- [ ] **Meaning-search cutoff** `MIN_SIMILARITY = 0.25` (`vl/index/search.py`). Too high misses notes, too low returns unrelated ones.
- [ ] **Sound confidence cutoffs**: tagger `--threshold 0.3` and `MIN_SOUND_CONFIDENCE = 0.3` (`vl/ask.py`). Both untuned.
- [ ] **Generic sound labels may need a higher bar** than baby-specific ones: `whimper 0.53` on a work call (user unsure if real), `giggle 0.35` in a work 1:1 (unknown), adult laughter counting as baby laughter. One example isn't enough to tune on; collect more.
- [ ] **Topic bonus** `TOPIC_BONUS = 0.2` for sound + transcript matches (`vl/ask.py`).
- [ ] **Keyword search is OR-of-any-word**, so common words ("sounds", "making") pull in irrelevant notes (HR coaching notes appeared for "baby making cute sounds"). Consider requiring 2+ matching words, phrases, or stop-words.
- [ ] **Rerank only sees the first 300 characters** of each transcript (`vl/ask.py`).
- [ ] **Claude's match / partial / related labels**: are they strict enough? Check on real queries.

## B. Not yet verified on real data
- [ ] **Dates**: only "Weija Gbawe" was checked by hand. The note `5:16:25, 2:50 PM.m4a` is dated 2020-01-14, which doesn't fit its name. Note numbering isn't in date order (192 is newer than 193); unexplained.
- [ ] **Transcript accuracy**: spot-checked ("look good for the most part"), not measured. Non-English speech / accents / names untested.
- [ ] **Cost and speed**: `process` time and Claude API cost never measured. Sound tagging speed is an estimate from timestamps (about 4 minutes for 16 notes, several hours of audio). `--device mps` untested.
- [ ] **Stored durations**: unknown whether the audio files carry them; `ask` falls back to approximate transcript timing and says so.
- [ ] **Natural-language dates** ("two weeks ago", "last summer") never tested through the real parser.
- [ ] **The two enrichment failures** ("no JSON object in model reply") went away after the retry fix, but the cause is unknown (retry, or a one-off).
- [ ] **Eval**: `eval` and `evalgen` have never run on the real library. Planned: record clips with known content/sounds, then score. LLM-written questions run optimistic.
- [ ] **Re-run safety on real data**: only tested with fakes.

## C. Planned but not built
- [x] **Category suggestions flow**: built (web page + `vl/library.py`). Still to check on real notes: are Claude's suggestions any good? Merge/rename of categories isn't built.
- [x] **Junk review queue**: built; archive only hides, never deletes. Still to check: is `junk_score >= 0.5` the right bar?
- [x] **Privacy switch** for the Claude steps: built in the page (server-wide, resets on restart). A per-step or per-category switch isn't.
- [ ] **Alembic migrations**: the schema is created with `create_all`, so changing an existing table's columns will NOT update the user's existing `library.db`. New tables are fine. Needed before any column change.
- [ ] **Apple Voice Memos sync** (investigate): read the Mac's library directly instead of dragging files out.
- [ ] **Record in the app**, then a **phone app** on the same API.
- [ ] **Full run on ~1,000 notes**: resumable batch exists; needs a time/cost estimate first.
- [ ] **Category-driven browsing in more depth** (merge/rename categories, move many notes at once).

## D. Housekeeping and fragility
- [ ] **`av<19` pin** in requirements: faster-whisper 1.2.1 breaks on av 19. Remove when it supports it.
- [ ] **torch 2.15 with torchaudio 2.11** installed side by side on the user's Mac. It works but isn't a matched pair; keep an eye out for load errors.
- [ ] **Test recordings are mixed into the real library**: `Red Fox Rd 10/11/12` (baby babbling, failed laugh, laugh). Decide whether to keep or archive them.
- [ ] **`docs/brief.md` is stale** (still says "idea", no eval/sound/web work). Run `/build-trail` wrap-up.
- [ ] **HF_TOKEN warning** on every run (harmless; set a token to silence it and speed up downloads).
- [ ] **`questions.example.json`** uses placeholder filenames from one library.
- [ ] **build-trail skill edits** (plan-mode section) live only in the user's synced skill copy; confirm they persisted at the source.

## E. Added with the web page (2026-11-16): untested on the real library
- [ ] The page itself has been exercised only against a made-up demo library in a headless browser, not on your notes or your Mac.
- [ ] **Audio playback of real `.m4a` files** (and seeking via the sound chip) is unverified in Safari/Chrome; the server supports range requests.
- [ ] **Sound results get no match/partial/related label or verdict** (they're ordered by detection confidence). Consider showing a plain-language confidence.
- [ ] **Quick search while typing loads the embedding model per server start** and runs one embedding per keystroke (debounced 250 ms); check it feels instant on the Mac.
- [ ] **The Claude switch is server-wide and resets on restart**; no login, so don't expose the port beyond 127.0.0.1.
- [ ] **No pagination** on category lists (first 100 notes) or search (top 8): fine for ~1,000 notes, revisit for more.
- [ ] **Archive/Keep have no undo toast**, only the Archived list; "Restore" works but Keep can't be un-kept.
- [ ] **Existing databases**: new `note_flags` table is created automatically; any future column change needs Alembic.

## F. Redesign build (2026-11-16)
- [x] **Theme**: restyled to ivory and slate (editorial, squarer corners, compact charcoal hero, serif titles, numbered rows). The earlier crimson/Harvard idea was rejected as too strong. Still to carry onto the mockup canvas: Search, Recording and Import in the new look (only Library is drawn). No dark mode any more (one look).
- [ ] **Top-4 collection cards** are the four largest by recording count; every collection is in the sidebar. Check this feels right with a real library (many small collections, or ties).
- [ ] **Import on the real Mac is unverified**: uploads, Whisper loading on the first import (slow start), sound detection loading, large files. Tested only with fakes and tiny files.
- [ ] **Upload date fallback**: the browser's file-modified time is used as a last-resort recording date (`date_source = file-modified`); for files dragged out of Voice Memos this may be the export time. Check the "Date from" row on a recording.
- [ ] **Import is one file at a time** (one worker); a big folder of ~1,000 notes will take hours and needs the app to stay running. No pause/resume button yet (the mockup shows Pause).
- [ ] **No per-file progress for titling/indexing/sounds**, only transcription (percentage).
- [ ] **Waveform is computed on first view** per recording (decode the whole file); long recordings may be slow the first time, then cached in `~/VoiceLibrary/cache/peaks`.
- [ ] **Related recordings need embeddings and a similarity cutoff (0.35, untuned)**; often empty with a small library.
- [ ] **Language** isn't stored (the mockup shows it); would need a schema change (Alembic).
- [ ] **Per-keystroke instant search** calls the embedding model; check it feels instant on the Mac.
- [ ] **Accessibility**: the faint search placeholder (#7F8B85 on ivory) is below 4.5:1 by the user's request; waveform has slider keyboard support but no screen-reader transcript sync.

## G. Voice Memos import and weak sounds (2026-11-16): unverified on the user's Mac
- [x] **Voice Memos library path** verified on the user's Mac (2026-11-17): the group-container path was right and 505 recordings were found.
- [x] **Full Disk Access** for Terminal was required and worked once granted and Terminal was fully restarted (2026-11-17). Still unchecked: whether any recordings exist only in iCloud (not downloaded to the Mac).
- [ ] **Titles in Voice Memos** (the names you gave recordings) live in a private database (CloudRecordings.db) and are not imported; files get their file name.
- [ ] **Why the baby clip wasn't found**: hypothesis is a laugh score below the old 0.3 floor. After `sounds --redo`, check whether the clip now appears as "possibly giggling". If it still doesn't, the model may not hear this child's giggle at all (home phone audio, overlapping babble).
- [ ] **Cutoffs 0.30 / 0.15** are guesses. More "possible" matches also means more false positives (e.g. adult chuckles in work calls); watch this.
- [ ] **Re-run needed**: existing sound events were stored at the old 0.3 threshold; run `python -m vl.cli sounds --redo` once.
- [ ] **Folder import hashes every file** to skip duplicates; a big library (1,000+ notes) re-imported repeatedly will re-read everything each time.

## H. Large import / full library (2026-11-16): the open priority
- [x] **Verify the Voice Memos folder can be read on the user's Mac** (path and Full Disk Access). Done 2026-11-17: 505 recordings found.
- [ ] **Time and Claude cost for ~1,000 notes are still unmeasured on the real Mac.** The test batch is built (reports time, tokens, an estimate; dollars only if prices are set) and verified against a demo library; run it on the user's Mac. The estimate is crude: it assumes the batch is typical and counts recordings already imported.
- [x] **Import order is newest first** (folder imports and sync). Built 2026-11-17.
- [ ] **No ETA, pause, resume or cancel** on a long import. The in-memory queue is lost if the app stops (sync re-submits unseen files; a manual import needs re-clicking).
- [ ] **One file at a time**: safe but slow; consider limited parallelism only if the machine has headroom.
- [ ] **Sync only runs while `vl serve` runs.** Start-at-login needs a launch agent and a decision on where the Claude API key lives (macOS Keychain, not a plain file).
- [x] **Sync verified in a real browser against a demo Voice Memos folder** (first sync imports all, a new file is picked up, no duplicates over repeated checks, originals untouched). Still unverified on the user's real Voice Memos folder.
- [ ] **Phone access** (through the Mac first, cloud copy later) needs login, a private connection (e.g. Tailscale), and an installable web app; not started.

## I. Test batch (2026-11-17)
- [ ] **Run it on the real Mac** and compare its estimate with what the full import actually takes.
- [ ] **Estimate caveats**: assumes the 25 newest are typical; remaining-audio length needs `mutagen` (falls back to the batch average); counts already-imported recordings in the remaining total.
- [ ] **Dollars need prices**: set `VL_PRICE_IN_PER_MTOK` and `VL_PRICE_OUT_PER_MTOK`; only the labelling Claude calls are metered (not search questions).
- [ ] **Still missing for the long import**: a live ETA while running, pause/resume/cancel, and a queue that survives an app restart.

## J. Waiting on results (2026-11-17)
- [ ] **Test batch on the real Mac is running**: its results card (time, Claude tokens, estimate for the other ~480) is the next thing to record. After it, refresh `docs/brief.md` (library size is 505, not ~1,000) and write the next progress report at the next wrap-up.

## K. Timing tool (2026-11-18)
- [ ] **`vl profile` is tested with fakes only**; run it on the Mac (`python -m vl.cli profile --voicememos 3`) and record the per-stage seconds. The first recording may be slower (warm-up); `--device mps` for sounds is untested.
- [ ] Decide the speed fix from its numbers (separate sound pass, smaller Whisper model, parallel Claude calls).
