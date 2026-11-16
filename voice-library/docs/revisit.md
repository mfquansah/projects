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
