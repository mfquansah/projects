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
