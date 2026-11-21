# Voice Note Library
Product brief | Version 3 | Updated: 2026-11-18 | Status: prototype (in use on the user's real library; bulk import under way) | Link: voice-library/ in mfquansah/projects

## 1. Product overview
A searchable personal audio library for voice recordings. It transcribes each note on your computer, writes a title, summary, category and tags with Claude, listens for sounds like a baby laughing or babbling, and lets you find a recording by describing it in plain language, then play it. It is a personal audio library, not a generic AI note-taking app. `[confirmed]`
It runs as a local web app (`python -m vl.cli serve`) with one big search box. A phone web app that mirrors it is the agreed next direction. `[confirmed]`

## 2. Problem statement
About 505 recordings (ideas, conversations, family memories; the user first guessed ~1,000) live in Apple Voice Memos, which only labels them by date and location. There is no tagging, categorization or search, so a specific recording (for example the baby laughing two weeks or two years ago) cannot be found, and most old notes are no longer remembered at all. `[confirmed]`

## 3. Target users
The builder, as the only user for now. Wants to find any recording quickly and to see what a note is without playing it. `[confirmed]`

## 4. Value proposition
Replaces paid tools (Granola, Pocket) with something free to run. Audio and transcription stay on the user's Mac; transcript text and questions are sent to Claude (always on, no switch) for titles, summaries and understanding questions. `[confirmed]`

## 5. Goals and success metrics (proposed until validated)
- Retrieve a specific recording from a natural-language question, with its title, summary, category and working playback. `[inferred]`
- A baby clip can be found fast (about 30 seconds). `[confirmed]`
- The whole library (505 recordings) is imported and kept in sync without manual work. `[confirmed]`
- Offered and not picked for the first-version bar: the right note near the top for most questions, and works on the phone too. `[confirmed]`
- Search quality is not yet measured: an eval runner exists but has not been run on real recordings (the user plans to record clips with known answers first). `[confirmed]`

## 6. MVP scope
**Built** (206 unit tests pass; a browser test drives every screen on a demo library):
- Import: Voice Memos library read in place (needs a macOS permission), a folder by path, or drag-and-drop of files/folders; automatic sync (opt-in, one-way, read-only). Per-file progress; a bad file never stops the rest; originals never touched. `[confirmed need]`
- Understanding each note: local Whisper transcript with timestamps; Claude title/summary/category/tags/junk score; recording date from filename, then the audio's metadata, then file times. `[confirmed]`
- Search: keyword, meaning, date, category/tag filters, sound filters (baby crying/laughing/babbling), sorting ("my longest", "newest"), natural-language questions parsed by Claude, results labelled Match / Partly / Related with a one-line verdict, matching moment shown with a timestamp. `[confirmed]`
- Recording page: waveform with markers where sounds were heard, timestamped transcript, editable title/summary/tags, related recordings, archive (never delete). `[confirmed]`
- Collections: seeded (Ideas, Family memories, Work & projects, Personal reflections, Other); Claude suggests new ones, the user accepts or dismisses, creates by hand or from a tag; a review queue for likely-accidental notes. `[confirmed]`
**Out of scope for now:** recording inside the app, a native phone app, cloud sync, start-at-login, dark mode, Windows/Android. `[inferred from the roadmap]`

## 7. Experience principles
- Find a thought, memory or recording by describing it. `[confirmed]`
- One box: type for instant local results, press Enter for the full answer. `[confirmed]`
- Minimal, calm and soft: ivory and slate, serif titles, rounded corners; not a research tool, and not a "Claude app" look. `[confirmed]`
- Suggest, never silently change or delete: archive only hides; sync is opt-in. `[confirmed/inferred]`
- Be honest about uncertainty: labels say Match/Partly/Related; weak sound matches say "possibly"; approximate lengths and fallbacks are stated. `[inferred]`

## 8. Release roadmap
1. Speech pilot (import, transcribe, label, search). **Done on real notes.**
2. Sound tagging. **Built; recall on a real baby giggle unconfirmed.**
3. Web page, redesigned. **Built; the real-library experience is only partly seen.**
4. Full import of the 505 recordings. **In progress: a 25-recording test batch took about an hour with no failures (about 9 s of work per minute of audio, ~384 minutes of audio); at that rate the rest is roughly 19 hours, so it is run in chunks ("next 100"). Newest first. Pause/resume and a live estimate are on the shelf.**
5. Voice Memos import and sync. **Import verified on the user's Mac (505 found, macOS Full Disk Access granted). Automatic sync is built and tested but its switch is shelved.**
6. Phone web app mirroring everything, reaching the library through the user's Mac first (a cloud copy later), then a native app with in-app recording. **Agreed; not started. Comes after the large import.** `[confirmed]`

## 9. Designs and work products
| Name | Link | Purpose | Status |
|---|---|---|---|
| Design canvas: "Voice Library mockups" | https://claude.ai/artifact/CH63RfVcq2bf6GxhBiaz6V (private) | Library, Search, Recording, Import, plus a revised Library in ivory and slate | Library (ivory/slate) is current; Search, Recording and Import are in the earlier sage look |
| The app | voice-library/web/ | The built UI (ivory and slate, softened) | Verified in a headless browser on demo data |
| Demo server + browser test | voice-library/tools/ | Fake library; drives every screen incl. upload, folder import and sync | Passing |
| Revisit list | voice-library/docs/revisit.md | Everything guessed, unverified or deferred | Current |
| Implementation plan (rev 2) | ~/.claude/plans/fluttering-wondering-pebble.md (session-local, not in the repo) | Original architecture and milestones | Approved 2026-11-15; since extended |

## 10. Key risks and assumptions
- Voice Memos folder location and macOS permission: verified 2026-11-17 (Full Disk Access had to be granted to Terminal and Terminal fully restarted). `[confirmed]`
- Time and cost: measured on 25 recordings (about 1 h; about 60,000 tokens in, 8,600 out); where the time goes is not yet known (the next batch reports it). Dollar cost not shown: prices are not set. `[confirmed]`
- Baby-sound detection on home phone audio: baby babbling was detected clearly; a giggle was not found, so weak detections are now kept ("possibly"). Cutoffs 0.30/0.15 are guesses. `[inferred]`
- Claude's match labels and meaning-search cutoff (0.25) are untuned. `[inferred]`
- Date from the browser's file-modified time (uploads) may be the export time. `[inferred]`
- Single copy of the library on the user's Mac: no backups yet. `[inferred]`
- Phone access needs a login and a private connection; not built. It only works while the Mac is on (accepted: the Mac is usually on). `[confirmed/inferred]`

## 11. MVP success definition
The user can import their whole library hands-off and keep it in sync, and can find a baby clip in about 30 seconds. `[confirmed]` Phone access and measured search accuracy are wanted but are not part of this first bar. `[confirmed]`

## 12. Next phase
The large import (confirmed as the next priority): confirm the app can read Voice Memos on the Mac, a 25-note test batch that reports time and Claude usage, newest-first order, an estimate, pause/resume and a queue that survives a restart; then the full import; then phone access through the Mac. `[confirmed]`
