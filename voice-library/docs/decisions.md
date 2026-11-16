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
