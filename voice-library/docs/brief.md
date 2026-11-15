# Voice Note Library
Product brief | Version 1 | Updated: 2026-11-15 | Status: idea | Link: voice-library/ in mfquansah/projects

## 1. Product overview
A free, local-first, searchable library for personal voice recordings. It transcribes each note, gives it a title,
summary, category and tags, and lets you find it later with a natural-language question and play the original audio.
It is a personal audio library, not a generic AI note-taking app. `[confirmed]`

## 2. Problem statement
About 1,000 recordings (ideas, conversations, family memories) live in Apple Voice Memos, which only labels them by
date and location. There is no tagging, categorization or search, so a specific recording (for example the baby
laughing about two weeks or two years ago) cannot be found. `[confirmed]`

## 3. Target users
The builder, as the only user for now. Wants to find any recording quickly and to see what a note is without playing it. `[confirmed]`

## 4. Value proposition
Replaces paid tools (Granola, Pocket) at no recurring cost, and keeps private family audio on the user's Mac. `[confirmed]`

## 5. Goals and success metrics (proposed until validated)
- Retrieve a specific recording from a natural-language query on a pilot of 20-30 notes. `[inferred]`
- Candidate metric, not yet agreed: any baby clip found in under 30 seconds. `[inferred]`

## 6. MVP scope
In: import existing recordings, transcribe, auto title, category, summary, search spoken content (keyword, meaning,
date, category/tag filters, LLM natural-language query), play original audio. `[confirmed]`
Categories seeded with Ideas, Family memories, Work & projects, Personal reflections, Other; the tool can suggest new
ones and the user can create them manually or from tags. `[confirmed]`
Out of scope for now: polished front end beyond a simple local web page, auto-sync with Apple Voice Memos,
recording in the app, phone app. `[confirmed]`
Sound detection (baby laughing/crying) comes right after the speech pilot, before the full run. `[confirmed]`

## 7. Experience principles
- Find a thought, memory or recording by describing it. `[confirmed]`
- Audio stays on the Mac; only text goes to the cloud LLM. `[confirmed]`
- Suggest, never silently change or delete. `[inferred]`

## 8. Release roadmap
1. Pilot on 20-30 notes, speech only, command line.
2. Sound tagging (baby laughing/crying) as first-class filters.
3. Simple local web page.
4. Full run on ~1,000 notes with a suggest-only review queue.
5. Later: Apple Voice Memos sync (investigate), record in app, phone app.

## 9. Designs and work products
| Name | Link | Purpose | Status |
|---|---|---|---|
| Implementation plan (rev 2) | ~/.claude/plans/fluttering-wondering-pebble.md (session-local) | Architecture and milestones | Approved 2026-11-15 |
| Concept mockup: personal audio library | pasted screenshot, not stored | Category cards + search + player idea | Illustrative only |

## 10. Key risks and assumptions
- File dates may not survive drag-out export from Voice Memos. Not verified. `[inferred]`
- Baby-sound classifier accuracy on home phone recordings is unproven. `[inferred]`
- Cannot test against the user's real recordings from the cloud session; pilot must run on the Mac. `[inferred]`
- Apple has no public bulk-access API for Voice Memos; design around exported files first. `[inferred]`

## 11. MVP success definition
Given 20-30 imported notes, a natural-language query returns the intended recording with its title, summary,
category and working audio playback. `[inferred]`

## 12. Next phase
Build milestone 1 (import, transcribe, enrich, search from the command line), then run it on a 20-30 note pilot on the Mac.
