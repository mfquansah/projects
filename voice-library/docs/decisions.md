# Decision log (append-only)

### 2026-11-12 - Build free instead of buying
- Decision: build a free library instead of using Granola or Pocket.
- Alternatives considered/rejected: Granola, Pocket.
- Why: user does not want to pay.
- Reversible? yes
- Source: confirmed

### 2026-11-12 - Local-first pipeline (Whisper, SQLite, embeddings)
- Decision: local transcription, SQLite full-text and embedding search.
- Alternatives considered/rejected: cloud transcription and hosted search.
- Why: proposed for cost and privacy; user had not approved it at the time. Later reinforced by the family-audio privacy point in the user's notes.
- Reversible? yes
- Source: inferred

### 2026-11-15 - Python, in a new voice-library/ folder
- Decision: Python pipeline in `voice-library/` in mfquansah/projects, matching ghana-resource-monitor conventions.
- Alternatives considered/rejected: Swift; separate repo.
- Why: best ML ecosystem (Whisper, audio tagging, embeddings); folder follows the repo's existing pattern. Swift was offered and not chosen.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Scale is about 1,000 notes
- Decision: design for ~1,000 notes (SQLite, brute-force vector search). The "~100k" in earlier notes was a slip.
- Alternatives considered/rejected: 5-10k and 100k designs (job queue, approximate vector index).
- Why: user confirmed ~1,000.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Import from exported audio files first
- Decision: import a folder of files the user drags out of Voice Memos; reading Apple's library directly is a later enhancement.
- Alternatives considered/rejected: reading the Voice Memos database from day one.
- Why: Apple has no public bulk-access API (from the user's product notes). Notes already sync via iCloud to the Mac, so no iPhone export is needed.
- Reversible? yes
- Source: confirmed (iCloud sync), inferred (file-first approach)

### 2026-11-15 - Cloud LLM allowed for text steps only
- Decision: audio and transcription stay on the Mac; transcript text and search queries go to the Claude API.
- Alternatives considered/rejected: fully local LLM.
- Why: user said sending transcripts to an LLM is fine.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Categories: seeded, extensible, suggest-only
- Decision: seed Ideas, Family memories, Work & projects, Personal reflections, Other. The tool may suggest new categories; the user can create them manually or from tags.
- Alternatives considered/rejected: fixed list only; fully AI-invented categories.
- Why: user asked for suggestions plus manual and tag-based creation.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Search: keyword, meaning, date, filters and LLM natural-language query
- Decision: support all of these in the first version; the LLM translates queries into filters and may rerank, but never searches audio.
- Alternatives considered/rejected: keyword only.
- Why: user selected all and asked for LLM natural-language search.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Sound tagging right after the speech pilot
- Decision: build baby laughing/crying detection as milestone 2, before the full run.
- Alternatives considered/rejected: include in the pilot; keep in "Later" as in the user's product notes.
- Why: finding baby clips is the main reason for the project; reason for choosing this timing over the others not recorded.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Simple local web page as the first interface
- Decision: a local web page (search, category cards, player) before any phone app, on an API the phone app can reuse.
- Alternatives considered/rejected: command line only; straight to a phone app.
- Why: reason not recorded beyond choosing the recommended option.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Plan rev 1 declined
- Decision: user declined the first plan and asked to discuss further.
- Alternatives considered/rejected: n/a
- Why: reason not recorded.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Plan rev 2 declined, then rev 2 approved
- Decision: user declined rev 2 several times while the nine-step walkthrough ran (wanted build-trail and plan-mode behavior discussed first), then approved it after the walkthrough.
- Alternatives considered/rejected: n/a
- Why: user wanted to discuss before executing; no further reason recorded.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - Build the natural-language query layer now
- Decision: build `ask` (LLM parses question into filters, hybrid search, optional LLM rerank) before running the pilot.
- Alternatives considered/rejected: wait for pilot results to see what's missing (my recommendation).
- Why: user asked to build it now; they chose it over my suggestion to wait, reason not recorded.
- Reversible? yes
- Source: confirmed

### 2026-11-15 - LLM translates and explains; it never searches or invents notes
- Decision: the LLM only produces filters and reranks database results. Invented ids are ignored, bad dates/categories are dropped with a visible note, LLM failure falls back to plain search, and empty filtered searches relax category then dates with a stated note.
- Alternatives considered/rejected: letting the LLM answer from transcripts directly.
- Why: keeps every result verifiable against the user's own notes. This was my design choice, not discussed with the user.
- Reversible? yes
- Source: inferred

### 2026-11-15 - Minimum similarity cutoff on meaning search (0.25, untuned)
- Decision: drop semantic matches below cosine 0.25. Found by a test: without it any query, even nonsense, returned unrelated notes.
- Alternatives considered/rejected: no cutoff.
- Why: nearest-neighbour search always returns something. The value 0.25 is a guess for all-MiniLM-L6-v2 and has not been tested on real notes; tune during the pilot.
- Reversible? yes
- Source: inferred

### 2026-11-15 - Pin av below 19
- Decision: require `av>=14,<19` in requirements.txt.
- Alternatives considered/rejected: upgrading av (already at 19.0.2, which caused the failure); patching faster-whisper.
- Why: pilot run failed all 19 notes with "open() got an unexpected keyword argument 'metadata_errors'". Reproduced in the cloud session: faster-whisper 1.2.1 calls av.open(metadata_errors="ignore"), which av 19 no longer accepts. av 18.1.0 through 14 decode fine (verified on a WAV file, not on real m4a).
- Reversible? yes (drop the pin once faster-whisper supports av 19)
- Source: confirmed

### 2026-11-16 - Build an eval runner before fixing search
- Decision: add `vl eval questions.json`, scoring `search`, `ask-norerank` and `ask` on the same user-written questions (hit@1/3/5, MRR, correct "nothing found", time, LLM calls).
- Alternatives considered/rejected: judging by hand-picked queries; scoring only `ask`.
- Why: user asked for a proper eval after the first manual query ("longest voice note") returned an unrelated note. Running search as a baseline was my suggestion, not discussed further.
- Reversible? yes
- Source: confirmed (eval), inferred (three-mode comparison)

### 2026-11-16 - Generate eval questions from the library instead of from memory
- Decision: add `vl evalgen`. Claude writes questions per note (answer = that note), property/date answers are computed from library data, "nothing" topics are kept only if absent from all transcripts, and the user reviews content questions against the note shown.
- Alternatives considered/rejected: user writes questions and answers from memory (impossible: they don't remember most notes).
- Why: user said they don't remember the contents of old notes, which is the reason for the project. Known weakness: LLM-written questions echo the note's wording, so scores are optimistic; real questions logged over time would be a better eval later.
- Reversible? yes
- Source: confirmed (need), inferred (design)

### 2026-11-16 - `ask` supports sorting by length and date
- Decision: the query parser outputs `sort` (longest/shortest/newest/oldest) and `count`. With a topic, matching notes are found first and then sorted; without one, all notes passing the filters are sorted. Sorted answers are never reranked. When a length is missing, the transcript's last segment end is used (approximate); notes with no information are left out and the output says so.
- Alternatives considered/rejected: leaving it as a known gap until after the recording tests.
- Why: the user's first real query ("longest voice note") returned an unrelated note, and they asked to build this next. The transcript-timing fallback is my choice; I never confirmed whether stored durations were populated on their Mac.
- Reversible? yes
- Source: confirmed (need), inferred (design)

### 2026-11-16 - Sound tagging with a local AudioSet model; sound is a filter in `ask`
- Decision: `vl sounds` runs an AST model trained on AudioSet over each note in 10 s windows, locally, and stores baby cry / crying / whimper, baby laughter / giggle / laughter, and babbling events (label, start, end, confidence). `ask` applies a sound as a filter: notes with that sound, ranked by confidence (a transcript match adds a small bonus), never reranked by Claude, and never relaxed to unrelated notes. If sounds haven't been analyzed, or the sound is unknown, the sound part is ignored and `ask` says so.
- Alternatives considered/rejected: YAMNet (faster, less accurate; not tested), PANNs, using only transcripts.
- Why: finding the baby clips is the main reason for the project (user, earlier), and transcripts can't find clips with no speech. Choice of AST over the alternatives was mine; it was not compared.
- Reversible? yes (model, cutoffs and labels are isolated in vl/sounds/)
- Source: inferred (model choice), confirmed (need)
- Not verified: speed on real notes, accuracy on real home recordings, the model's exact label names (HF blocked from the build session, so labels are matched by keyword), and the 0.3 cutoffs.

### 2026-11-16 - Require torchaudio for sound tagging; add `sounds --inspect`
- Decision: add torchaudio to requirements, warn loudly when it is missing, and add `vl sounds --inspect FILE` to show what the model hears in one file with no cutoff.
- Alternatives considered/rejected: treating the "mel filter has all zero values" warning as harmless (my first assumption, wrong).
- Why: the user's real laughing test clip produced 0 events. Reading the transformers source showed that warning appears only when torchaudio is missing, so the model was receiving approximate features. Not yet confirmed that this is why the clip was missed; loudness of the clip is another candidate.
- Reversible? yes
- Source: inferred

### 2026-11-16 - Sound search no longer depends on the parser; rerank now drops what Claude didn't endorse
- Decision: (A) tell the parser that baby sounds/cooing/babbling mean `baby_coo`, and add a keyword fallback (`infer_sound`: a baby/child word plus a sound word) that runs when the parser sets no sound or the LLM is down. (B) After rerank, return only the results Claude endorsed (with a note saying how many were set aside); if it endorsed none, keep plain search order.
- Alternatives considered/rejected: relying on the parser prompt alone; (B) keeping unendorsed results at the bottom, which was my earlier choice.
- Why: on the user's real notes, "my baby making cute sounds" found the baby clip only through the transcript while a strong baby_babble 0.84 went unused, and three irrelevant HR-coaching notes were listed below the right answer. Reverses the earlier "omitted candidates stay" decision because real output showed it read as broken. Raising confidence cutoffs for generic labels (whimper/crying/giggle) was considered and deferred: one possible false positive (whimper 0.53 on a work call, unconfirmed by the user) is not enough to tune on.
- Reversible? yes
- Source: confirmed (user approved fixes A and B), inferred (design details)

### 2026-11-16 - Label each result match / partial / related and print a verdict
- Decision: the rerank step now returns a strength per result with strict definitions; results are ordered strongest label first (Claude's order within a label); `ask` prints `Result: One clear match.` / `N likely matches.` / `No clear match; ...`, computed from the labels. No labels (rerank off, failed, or the model omitted them) means no badge and no verdict. Sound and sorted answers are not labelled.
- Alternatives considered/rejected: a numeric confidence score (Claude's numbers would look precise but aren't calibrated); leaving the flat list.
- Why: user asked how they'd know which result is the right answer when several are listed; the real output had no indication of certainty beyond reading the "why" lines.
- Reversible? yes
- Source: confirmed
- Not verified: how often Claude's labels are right on real notes, and whether "match" is used strictly enough; check during the recording tests.

### 2026-11-16 - Single-box local web page (milestone 3), curation features included
- Decision: `vl serve` runs a FastAPI app and one HTML page on 127.0.0.1 only. One search box: typing runs local search; Enter runs `ask`. Also built the confirmed-but-missing pieces: accept/dismiss suggested categories (dismissals remembered), create a category by hand or from a tag, a review queue for likely-junk notes with Keep/Archive, an Archived list with Restore, and a server-wide "Use Claude" switch (Claude off = everything local). Archive hides a note from search, ask, sorting, sound results and counts; it never deletes the audio or data.
- Alternatives considered/rejected: a separate search and ask form (user: one form only); real deletion (unsafe for irreplaceable recordings); exposing the page on the network (family audio, no login).
- Why: the user asked for one box (confirmed), and asked to build as fully as possible before testing details. Archive-not-delete, localhost-only and the Host-header check are my safety choices, not discussed with the user.
- Reversible? yes
- Source: confirmed (single box, categories flow, review queue, privacy), inferred (safety choices, layout)

### 2026-11-16 - Redesigned app from the mockups; no Claude on/off switch
- Decision: rebuild the page to follow the mockups (sidebar, big serif search box, Library, Search results, Recording, Import, Needs attention). Claude is always used: the switch was removed. With no API key the page says so and falls back to basic search. Added what the mockups need: timestamped transcript, waveform (computed server-side, cached), related recordings, editable title/summary/tags (edits recorded and re-indexed), search snippets with timestamps, example searches from the library itself, and file upload with a background importer. The search prompt is upright serif and slightly faint, with a pulsing waveform glyph.
- Alternatives considered/rejected: keeping the privacy switch (user: "it uses Claude, and that's it"); a JS framework (kept plain ES modules, no build step, so the API stays reusable for a phone app).
- Why: user's direction on the mockups ("build on this mockup and improve it", minimal, serif search prompt, upright and faint). The honest privacy line replaces the mockup's "nothing is uploaded", because transcript text does go to Claude.
- Reversible? yes
- Source: confirmed (switch, serif prompt, style), inferred (architecture, import design)

### 2026-11-16 - Visual theme: ivory and slate, editorial
- Decision: soft ivory background with slate/charcoal accents (no red or maroon), serif titles, small letter-spaced capitals with an underline rule for section heads, numbered rows with hairline dividers, square-ish corners (3px). The Library screen has a compact charcoal hero with the large search box straddling its edge, the four largest collections as cards, and recent recordings; the sidebar lists every collection with counts, plus Needs attention. Dark mode was dropped so there is one consistent look.
- Alternatives considered/rejected: the sage-and-cream look (read as a Claude app); a Harvard-style crimson masthead and full-height hero (too strong, user: "not crazy Harvard red", hero "too prominent").
- Why: user's feedback on the references (Harvard, GoShuin) and on theme B: keep the ivory base and list rendering, drop the red, shrink the hero, bring back the sidebar and collections.
- Reversible? yes (colours are CSS variables in web/app.css)
- Source: confirmed

### 2026-11-16 - Softer corners and a calmer feel
- Decision: radius scale 6/10/16/24px (was 3-4px). Cards 16px, search box and drop zone 24px, buttons and inputs 10px, tags and chips are pills. The hero is a rounded panel inset from the edges (not a full-bleed band), the search box loses its heavy bottom bar for a soft shadow and a faint glow on focus, hairlines are lighter, the hero slate is a little lighter, rows have more air.
- Alternatives considered/rejected: the sharper 3px corners (read as a research tool, user: "make the overall feel softer ... beautiful and calming").
- Why: user feedback after seeing the ivory/slate restyle.
- Reversible? yes (--r-xs/sm/md/lg in web/app.css)
- Source: confirmed

### 2026-11-16 - Import straight from Voice Memos / a folder path; keep weak sound detections
- Decision: (1) The page can import from the Mac's Voice Memos library (and from any folder path) by reading files in place through the local server. Originals are never copied-then-deleted or modified (uploads are the only files deleted, and those are temp copies). macOS access problems return a clear fix (Full Disk Access) instead of failing quietly, and a drag-and-drop that delivers no files now says why. (2) Sound events are stored down to 0.10 confidence; searches treat >=0.30 as heard, 0.15-0.30 as "possibly" (ranked after confident ones), and ignore the rest. `vl sounds --redo` re-checks everything. Words about the request itself ("looking", "audio") are no longer highlighted.
- Alternatives considered/rejected: reading Voice Memos' private database for titles and dates (schema unverified; dates already come from the file name/audio); making drag-from-Voice-Memos work in the browser (not possible: file promises); keeping the 0.3 storage cutoff (a faint baby giggle was lost for good).
- Why: user's drag from Voice Memos did nothing, and a search for a child giggling didn't find their baby recording. Cause of the second is a hypothesis (laughter scored under 0.3); not yet confirmed on their data.
- Reversible? yes
- Source: confirmed (problems), inferred (causes and design)

### 2026-11-16 - Automatic sync with Voice Memos (opt-in, one-way, read-only)
- Decision: a background check (default every 10 minutes) imports new recordings from the Voice Memos folder. Off until the user turns it on, with an explicit confirmation showing how many recordings will be imported. Remembers (size, modified time) per file so checks are cheap; a file counts as seen only after a successful import; failures are retried up to 3 times; recordings changed after import are reported, not re-imported; iCloud-only recordings are counted and reported. Status shows in the sidebar.
- Alternatives considered/rejected: starting automatically (a first sync can import ~1,000 notes: hours and Claude usage); re-hashing every file each check; re-importing edited recordings as new notes (duplicates).
- Why: user wants everything imported and kept in sync while still using Voice Memos; their Mac is usually on. Phone access (through the Mac, cloud later) is the next planned step.
- Reversible? yes
- Source: confirmed (need, sequence), inferred (design details)

### 2026-11-16 - Recording dates: filename first, then the audio's own metadata, then file times
- Decision: derive a recording's date from a date in its filename, else the creation time stored inside the .m4a, else file times. `date_source` records which was used, `status` warns when file times were used, and `redate` fixes already-imported notes without ever replacing a date with a file-time guess.
- Alternatives considered/rejected: trusting the file's birth time (my first implementation).
- Why: in the user's pilot all 19 imported notes were dated to the export time, and Voice Memos names ("New Recording 192") carry no date. After the fix the dates spread across 2020-2026 and the one note the user could check (Weija Gbawe) matched.
- Reversible? yes
- Source: confirmed (the problem and the one-note check), inferred (design)

### 2026-11-16 - Proper search evaluation waits for new recordings with known content
- Decision: stop spending time on testing search quality now. Later, the user records clips with known content and sounds, and the eval runner and question generator are used on those.
- Alternatives considered/rejected: asking the user to write test questions with expected answers from memory (they don't remember most old notes).
- Why: user: "the way we will do the eval testing is once we've built it to a good point. we will make recordings, and then test."
- Reversible? yes
- Source: confirmed

### 2026-11-16 - Phone direction: a web app that mirrors everything first; cloud sync acceptable later; keep Voice Memos for now
- Decision: the phone starts as a web app that mirrors everything the desktop app does. The user keeps using Voice Memos for now; recording inside the app (and retiring Voice Memos) is later. Syncing through a cloud service is acceptable to them. Their Mac is "often at home / always on".
- Alternatives considered/rejected: a native iPhone app first (iOS has no way to read Voice Memos directly); copying the library to a hosted service first (bigger build, recordings on someone else's servers).
- Why: user's answers to the sync questions. How the phone reaches the library is NOT decided: I recommended going through the user's Mac first (fast, audio stays local, reuses the screens); the user asked why and has not chosen.
- Reversible? yes
- Source: confirmed (direction), inferred (the Mac-first recommendation)

### 2026-11-16 - build-trail skill observes during plan mode and doesn't repeat questions
- Decision: the skill gets a "Plan mode and prior planning" section: in plan mode it drafts in memory and writes nothing, decides from earlier answers whether to observe or ask, never repeats an answered question, skips the "start building or think more" card when the user is planning on purpose, and logs a declined plan as a decision.
- Alternatives considered/rejected: leaving the skill as it was (it always wrote files and asked its own questions).
- Why: user: build-trail "should just observe" in plan mode and take context from it. They approved the drafted wording ("looks good"). The edited skill lives in the user's synced skill copy; whether it persisted at the source is unverified.
- Reversible? yes
- Source: confirmed

### 2026-11-16 - Success definition for the first version
- Decision: the first version "works" when (1) a baby clip can be found fast (about 30 seconds) and (2) the whole library (~1,000 recordings) is imported and kept in sync hands-off.
- Alternatives considered/rejected: "the right note comes back near the top for most questions" and "works on my phone too" were offered and not picked; that does not mean they are rejected, only that they aren't part of the first-version bar.
- Why: reason not recorded beyond the user's selection.
- Reversible? yes
- Source: confirmed

### 2026-11-16 - Next priority: the large import first
- Decision: work next on the large import: confirm the app can read Voice Memos on the Mac, run a 25-note test batch that reports time and Claude usage per note, make the long import safe (newest-first, estimate, pause/resume, queue that survives a restart), then import everything.
- Alternatives considered/rejected: phone access first; tuning search and sounds first.
- Why: reason not recorded beyond the user choosing the recommended option. (My reasoning, not the user's: it blocks the success definition and the phone work.)
- Reversible? yes
- Source: confirmed

### 2026-11-16 - Phone reaches the library through the user's Mac first
- Decision: the phone web app connects to the Mac that runs the library (private connection, login, installable web app) before any cloud copy. Supersedes the "approach undecided" note in the phone-direction entry above.
- Alternatives considered/rejected: copying the library to a hosted service now; leaving it open.
- Why: reason not recorded beyond the user choosing this after asking why it was recommended. The recommendation's stated reasons were speed, reuse of the existing screens, and audio staying on the user's computer, with the cost that the phone only works while the Mac is on.
- Reversible? yes
- Source: confirmed

### 2026-11-17 - A timed test batch before the full import; newest-first everywhere
- Decision: the Import screen gets "Try a test batch (25 newest)": it imports the newest recordings not yet in the library, records seconds per step per file and Claude tokens per file, and shows a results card (time, speed per minute of audio, tokens, failures, and an estimate for the remaining recordings, with a one-click "Import the remaining N"). Dollar figures appear only if the user sets per-million-token prices in two environment variables; otherwise tokens only. All folder imports and sync now go newest first.
- Alternatives considered/rejected: hard-coding Claude prices (I don't know the current price of the model and it changes); estimating from file count only (note lengths vary a lot, so the estimate uses audio length when it can read it); importing everything blind.
- Why: the user agreed the large import is the next priority and approved the test-batch idea ("sure, go for it"); the time and cost of ~1,000 notes were unmeasured.
- Reversible? yes
- Source: confirmed (priority and the batch), inferred (design details)

### 2026-11-17 - Shelve the sync switch in the UI; the user grants the macOS permission by hand
- Decision: hide the "Keep in sync with Voice Memos" panel and the "Auto-sync is off" sidebar link. The sync backend, API and tests stay. Add `docs/build-later.md` as a shelf for deferred features. The user will turn on Full Disk Access themselves in System Settings.
- Alternatives considered/rejected: keeping the button (it was disabled while macOS blocked access, and didn't look disabled); making the app change the macOS setting (an app can't grant itself that permission; at best it can link to the settings pane, which is on the shelf).
- Why: user: "since we have to go through the settings ... not what we're testing now. Let's shelf it in our build later folder."
- Reversible? yes (flip `SHOW_SYNC_PANEL`)
- Source: confirmed

### 2026-11-17 - Page background #F2F0EF with neutral surfaces
- Decision: the app background is #F2F0EF (a cooler grey than the earlier warm ivory #F4EEDD). Surfaces, nav highlight, tag fills, hairlines and the hero text were retuned to neutral greys so nothing looks yellow on it; the slate hero and accents are unchanged. The Library mockup on the design canvas was recoloured to match; the other mockups were not.
- Alternatives considered/rejected: changing only the background (it left warm cream surfaces clashing with the cool grey; the user then agreed to tune the rest).
- Why: user: "change background to #f2f0ef", then "yup. go for it" to harmonising the rest. Reason for the colour itself not recorded.
- Reversible? yes (CSS variables at the top of web/app.css)
- Source: confirmed

### 2026-11-17 - Real library size is 505 recordings; Voice Memos access confirmed on the user's Mac
- Decision: plan for 505 recordings, not ~1,000. This supersedes the "scale is about 1,000 notes" assumption; the design (SQLite, brute-force vector search) is unaffected. The Voice Memos folder location was right, and macOS Full Disk Access had to be granted to Terminal (and Terminal fully restarted) before the app could read it.
- Alternatives considered/rejected: n/a (an observation, not a choice).
- Why: after the user granted the permission, the Import screen reported "505 recordings found" and showed the test-batch and import-all buttons. The user's earlier figure was from memory.
- Reversible? n/a
- Source: confirmed (the app's own count, seen in the user's screenshot)

### 2026-11-18 - "Import the next 100" now; batching is a build-phase measure, the product syncs
- Decision: add an "Import the next 100" button (the newest 100 recordings not yet imported, with the same timing and usage report) and continue the real import in chunks while we measure. In a finished product the user would not pick batches: connecting Voice Memos starts a background catch-up of the whole library (newest first, with progress and an estimate, pausable), after which sync keeps it current.
- Alternatives considered/rejected: importing all 505 in one go (about 19 hours at the measured rate, no pause button yet); fixing speed before importing more (the report's "where the time went" needs the next batch to tell us).
- Why: user: "let's do the next 100. but this is only because we're building the first one. in more product-ready builds ... we will sync, right?" I confirmed, and noted the first catch-up remains and speed matters more for it.
- Reversible? yes
- Source: confirmed

## 2026-11-18 - Build a timing tool (`vl profile`) before changing anything for speed
- Decision: add `python -m vl.cli profile` that runs a few recordings through every stage in a throwaway library, times model loading and each stage separately, and names the slowest stage. Shelve the blog notes and the morning to-do feature for now and work on speed.
- Alternatives considered/rejected: waiting for the next-100 results card (same answer, hours later); guessing the slow stage (transcription and sound detection were only my guess).
- Why: user: "let's shelf blog notes and morning to do for now. Let's work on the speed", then "yes, build the timing tool". Minutes instead of hours to learn where the time goes.
- Reversible? yes
- Source: confirmed

## 2026-11-20 - Shelve permanent delete and the exclusion list
- Decision: do not build a permanent delete button or an exclusion list now; the user will decide at the end. Archive (hide, restorable) stays the only removal.
- Alternatives considered/rejected: building delete with a "won't come back" fingerprint now.
- Why: user: "let's shelf that as well. that's stuff I'll decide on in the end."
- Reversible? yes
- Source: confirmed

## 2026-11-20 - Skip recordings longer than 45 minutes at import
- Decision: folder, Voice Memos and sync imports skip recordings longer than a limit (default 45 minutes; `serve --max-minutes N`, 0 = off). Skipped before copying or transcribing, so nothing is sent to Claude. A file whose length can't be read is kept. The results say how many were skipped. Drag-and-drop uploads are not limited (a deliberate choice by the user).
- Alternatives considered/rejected: importing everything; a delete or exclusion list (shelved by the user).
- Why: user: "is it possible to not import files longer than 45 minutes? those are most likely work meetings." Measured on the user's Mac: 42 of 499 recordings are longer, adding up to 55.9 hours of audio (roughly 9 hours of processing at the measured rate, about half the estimate for the rest of the library). Source of the 9 hours: audio minutes times 9.4 seconds, not a new measurement.
- Reversible? yes (raise or turn off the limit; skipped files are picked up on the next import or sync)
- Source: confirmed

## 2026-11-20 - Build permanent delete (un-shelved)
- Decision: a "Delete permanently..." button on the recording page, with a confirmation. It removes the library's data and its own copy of the audio (never the original in Voice Memos) and remembers the recording's fingerprint so imports and sync skip it ("Skipped: you deleted this recording earlier"). Archive stays as the reversible option. No bulk delete yet.
- Alternatives considered/rejected: leaving it shelved (the earlier shelving the same day was reversed by the user); deleting without remembering the fingerprint (the next sync would bring it back).
- Why: user: "no let's add the delete button. I want to get rid of some things at some point."
- Reversible? no for the deleted recording (the original in Voice Memos can be imported again only if the fingerprint record is removed from the database by hand); the feature itself yes.
- Source: confirmed

## 2026-11-20 - Greeting uses the user's name, kept outside the code
- Decision: the hero greeting reads "Good evening, <name>". The name is set once with `serve --name <name>` and saved in `~/VoiceLibrary/profile.json`, not in the repository.
- Alternatives considered/rejected: hard-coding the name in the page (it would be in the repository).
- Why: user: "to the greeting.. we can add Good evening, Michael .. like my name."
- Reversible? yes
- Source: confirmed

## 2026-11-20 - Share a recording by email (Mail draft) or download
- Decision: a "Share..." panel on the recording page with an optional recipient, an optional message and optional summary/transcript. "Open in Mail" opens a draft in the Mac's Mail app with the audio attached under a readable name, and the person presses Send. "Download audio" saves the file under a readable name (for Gmail and others). The app never sends email itself and stores no email password. A warning shows above 20 MB.
- Alternatives considered/rejected: the app sending the email over SMTP (it would have to store an email or app password, a real security risk for a private library); a mailto link alone (can't attach a file).
- Why: user: "are we able to share audios? if not, let's create a share button that shares by email, and then we can optionally add a message", then chose "Apple Mail app ... but I'd also like a download, so I can do gmail".
- Reversible? yes
- Source: confirmed

## 2026-11-20 - The sidebar lists only the five biggest collections
- Decision: the sidebar shows the five collections with the most recordings, then a "See N more collections" control that expands the list ("Show fewer" folds it back). A collection you are viewing stays visible even if it is not in the top five. The home page's four cards are unchanged.
- Alternatives considered/rejected: listing every collection (it keeps growing as Claude suggests new ones).
- Why: user: "the collections list is growing in the side bar. let's keep it at perhaps 5.. starting with the most in the collection, and then a little 'see more collections' to expand the list."
- Reversible? yes (one constant, `SIDE_COLLECTIONS` in `web/js/app.js`)
- Source: confirmed
