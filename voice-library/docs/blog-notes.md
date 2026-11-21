# Blog notes (living)

Raw material for a post about building the Voice Note Library with Claude Code and the build-trail skill. Updated 2026-11-18; add to it at each checkpoint.
Everything here comes from the decision log, the revisit and build-later lists, the git history, or this working session. Things I'm unsure of are marked.

## Privacy rules for the post
- Use the **demo library** (`tools/demo_server.py`) for every screenshot. The real library holds private material (family, the baby, work and HR conversations, job searches). Do not publish real titles, summaries, transcripts, names or search queries from it.
- No API keys, file paths with your username, or screenshots of the terminal with keys. Quotes from you below are verbatim; tidy typos and get your OK before publishing.

## The story in one paragraph
Hundreds of voice notes sit in Apple Voice Memos, which only labels them by date and location, so nothing can be found and most old notes are forgotten. We built a free, local-first library: transcription on the Mac, Claude for titles/summaries/search understanding, sound detection for things like a baby laughing, and a calm one-box web app. Along the way we kept the "why" in a build trail (brief, decision log, progress reports, a guesses list and a shelf), which is what this post is about.

## Timeline (2026)
| Date | What happened |
|---|---|
| Nov 12 | An idea and a first brief from a pasted status block. First decision: build it free, don't buy Granola or Pocket. |
| Nov 15 | Plan mode with questions. Plan rev 1 and rev 2 were declined while you wanted to talk it through; a nine-step walkthrough, then approval. Your own product notes reframed the MVP (speech first, sound later). First pilot on your Mac. |
| Nov 15 | Pilot problems on real notes: install timeouts, a lost virtual environment, tests that passed on Linux and failed on a Mac, every date wrong (the export time), a dependency update that broke transcription. |
| Nov 16 | Natural-language questions, an eval runner, sorting, sound detection, match labels, the first web page, then a full redesign from mockups on the Design canvas. |
| Nov 16 | The look: sage cream, then a Harvard-like crimson (too strong), then ivory and slate, softer corners, background `#F2F0EF`. |
| Nov 17 | Importing for real: dragging out of Voice Memos fails in a browser, macOS blocks the folder until you grant it, then 505 recordings found. A 25-recording test batch: about an hour, no failures. |
| Nov 18 | "Import the next 100". Questions about speed, and a new idea: a morning to-do note that becomes a task list. |

## Our process for tradeoffs (emergent, not designed)
Five habits repeated, and I'd say so honestly in the post:
1. **Recommend, then ask.** A recommended option first; you chose. Sometimes you overrode it (kept both `search` and `ask`; removed the Claude switch; shelved the sync switch).
2. **Write the tradeoff down in a fixed shape.** Decision, alternatives, why (or "reason not recorded"), reversible?, and whether you **confirmed** it or I **inferred** it. "Never invent rationale" is a rule of the skill and it showed: several entries say "reason not recorded".
3. **Reversibility as a tiebreaker.** Archive, never delete. Sync is opt-in. Imports are read-only. The shelved sync switch is one flag.
4. **Measure before committing.** The test batch came before the bulk import. It found the library is 505 recordings, not ~1,000, and gave real numbers (see below).
5. **Say what's unverified.** Two lists: `revisit.md` (guesses and unverified things) and `build-later.md` (features we chose to defer). Different jobs, so different files.

The criteria that actually decided things, again and again: **privacy, your stated priority, time and cost, and reversibility.** We never scored options against weighted criteria. That's a gap worth admitting.

## Tradeoffs we made (see `decisions.md` for the full entries)
| Tradeoff | Chose | Over | Who decided |
|---|---|---|---|
| Where to process | Audio and transcription on the Mac; only text to Claude | Cloud transcription (faster, but uploads family audio) | Confirmed (cloud LLM for text OK), reasoning inferred |
| Claude on/off switch | Always on, with a clear notice if no key | A privacy switch I'd built | You: "it uses Claude, and that's it" |
| Search and ask | Kept both in the code; one box in the UI | Two separate forms | Confirmed |
| Deleting notes | Archive only, nothing deleted | A delete button | Me (safety), not discussed |
| Sync | Built, opt-in, one-way, read-only | Starting automatically (a first sync imports everything) | Confirmed need, inferred design |
| Sync switch in the UI | Shelved | Keeping a button that was disabled behind a macOS permission | You: "shelf it in our build later folder" |
| Weak sound detections | Keep them, label "possibly", rank lower | Throwing away anything under 0.3 (a baby giggle was lost) | Inferred from a real miss |
| Importing 505 recordings | A timed test batch, then chunks | One blind bulk import (about 19 hours at the measured rate) | You approved |
| Phone | Web app through the Mac first | Cloud copy now / native app first | You (after asking why) |
| Dates | Filename, then the audio's own metadata, then file times | Trusting file times (all 19 were the export time) | Fixed after real data |
| Design | Ivory/slate, soft | Sage cream, Harvard crimson | Your feedback each round |

## Things that were hard
- **Pausing to think vs building.** The build-trail skill has a "start building or think once more" card, and it collided with plan mode: both ask questions, and the skill wanted to write files where plan mode forbids it. We rewrote the skill to observe in plan mode and never repeat an answered question. You also said, mid-build, "I didn't ask you to build anything yet. take a pause". Following your lead is a design constraint.
- **You don't remember your own notes.** That's why the project exists, and it broke the usual testing approach ("write questions with known answers"). So the eval questions are generated from the library itself, and real evaluation waits for new recordings with known content.
- **The platform, not the code.** Dragging from Voice Memos does nothing in a browser; macOS blocks the folder until Terminal has Full Disk Access and has been fully restarted; iOS can't read Voice Memos at all.
- **Honest numbers.** I would not guess Claude's price; the report shows tokens and only shows dollars if you set prices.

## Bugs found, and how (a good section: who/what caught it)
| Bug | Found by |
|---|---|
| All 19 imported dates were the export time | Your real notes |
| `av` 19 broke every transcription (`metadata_errors`) | Your real run; reproduced here before fixing |
| Recording date missed when the metadata block follows the audio | Reading my own code after the first fix didn't work |
| "giggling" didn't match "giggle" | A unit test |
| A single search result got no label | An API test |
| A worker shutdown race that could strand an upload | Reviewing my own code |
| Logo and waveform shared a CSS class; "null" and "[object ...]" printed on screen | A screenshot review (the test hadn't looked for it) |
| Sideways scroll on phones | The browser test |
| Dragging from Voice Memos silently did nothing | You |
| Results card had huge blank gaps | Your screenshot |
| A test failed because two test files had identical bytes | The test, correctly; the data was wrong |
| A commit pushed with a failing test | Me, my chained command didn't stop; fixed right after |
Also worth telling: my first guess was wrong twice (the Whisper model "hadn't downloaded"; the mel-filter warning was "harmless"). Reproducing the failure before explaining it fixed both.

## Design with Claude Design (the story)
- Mockups first, on a canvas; you brought your own earlier mockup, and I improved it (more minimal).
- Your notes, in order: search box 1.5× taller; the prompt in serif, upright and a bit faint; "it looks like a Claude app, I don't want that"; references (Harvard's Neurobiology page, GoShuin); crimson "too strong", hero "too prominent"; show collections on the welcome screen and keep the sidebar; "the curves are quite sharp ... beautiful and calming"; background `#F2F0EF`.
- What we learned: the real app needed its own pass after the mockup (the mockup was drawn once; the build then needed softening, neutral tints). Screenshots from the real build caught what the mockup hid.
- The canvas only has the Library redone in the final look (the other mockups are the earlier sage look): say so.

## Testing story
- 10 unit tests at the first milestone, 225 now. Fakes for Whisper, Claude, embeddings and the sound model, so nothing needs a download.
- A browser test (Playwright) drives every screen on a demo library: search, the recording page, editing, upload, folder import, the test batch, sync, phone width. It fails on console errors, stray "null" text and horizontal scroll.
- Real-world measurement: the 25-recording test batch (numbers below).
- Not yet done: measured search accuracy (waiting for recordings with known answers) and the baby-giggle search on the real library.

## Real numbers so far
- 505 recordings found in Voice Memos (we had assumed ~1,000).
- Test batch: 25 recordings, about 1 hour total, about 2 minutes each, slowest 9 minutes, about 9 seconds of work per minute of audio (384 minutes of audio), no failures. Claude: 23 calls, about 60,000 tokens in and 8,600 out (two recordings had no speech, so no call).
- If the rest look like this: roughly 19 hours (a crude estimate: the card uses the real file lengths).
- Where the time goes: not yet known. The next batch reports it.

## Quotes (verbatim; clean up and ask first)
- "There doesn't have to be a claude on and off switch. it uses claude. and that's it."
- "I want the UI to be beautiful and calming to look at."
- "I don't want it to look like a claude app."
- "let's take things step by step. follow my lead."
- "let's shelf it in our build later folder."
- "in more product-ready builds, we will roll out without having to import in batches. we will sync, right?"

## Still to capture
- Result of the next 100, and the time breakdown.
- Whether the baby giggle search works after `sounds --redo`.
- Which speed fix (if any) we try, and what it changed.
- The morning to-do feature: what we decide and build.
- What we'd do differently (draft: ask earlier which platform pieces are possible; build the long-import comforts before the first big import; log decisions when they happen, not at wrap-up).

## Shot list (demo data only)
Library (hero, search, collections); search results with Match labels and a timestamp chip; the recording page (waveform, sound marker, transcript); Import with the test-batch card; the design canvas across rounds; an excerpt of `decisions.md`; the two lists side by side (`revisit.md` and `build-later.md`).

## Possible shape of the post
1. The problem and why a build trail. 2. How we decide (the five habits, the table). 3. The look: design rounds. 4. Testing: what caught what. 5. The platform surprises. 6. Numbers. 7. What's unfinished, on purpose.
