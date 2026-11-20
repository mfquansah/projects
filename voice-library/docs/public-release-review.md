# Public release: what to review (private; not copied into the public folder)

The clean copy lives in `public-release/` and is rebuilt with `python tools/make_public.py` (it starts from scratch each
time, scans for personal details, and refuses to finish if it finds any). Nothing in the real project was changed except
the small additions listed at the bottom.

## Your decisions so far
- Licence: **MIT** (copyright line is "Michael Quansah": please confirm or correct it in `public-release/LICENSE` and in
  `tools/make_public.py`).
- Name "Kasa Adaka" and the logo stay yours (`public-release/BRAND.md` says forks should rename and use their own logo).
- Build trail: cleaned copy for you to read before deciding whether it goes public. It is in `public-release/docs/`.
- Not decided yet: whether to publish at all, and when. The folder is only a preview.

## Left out of the public copy
- `docs/blog-notes.md`, `docs/blog-draft.md` (personal, and the blog is yours to publish your way)
- `docs/progress/` (progress reports mention real recordings)
- `docs/.build-trail-state`, `tools/render_trail.py`, `tools/trail_template.html` (the page renderer for the private trail)
- this file

## Rewritten (each one is checked, so the script fails if the source line changes)
- real recording names (a place name, three test recordings, a recording with a time as its name) became generic wording
- "HR coaching notes" became "unrelated work notes"
- your repository path and your other project's name were removed
- "Michael" in examples and tests became "Ama"; example recording names in `questions.example.json` became invented ones

## Read these in `public-release/docs/`
- `decisions.md`: it quotes you ("Why: user: ...") dozens of times. The quotes are verbatim and mostly harmless, but they
  are your words, so decide if you are happy to publish them. This is the main thing to read.
- `revisit.md`, `build-later.md`: honest lists of guesses and shelved ideas. They mention the baby, family recordings and
  "work meetings" in general terms.
- `brief.md`: the product brief.
- `manual.md`.

## Before publishing (when you decide)
1. Read the docs above and tell me what to cut.
2. Create an empty repository on GitHub (I cannot create repositories from here).
3. Push the **contents** of `public-release/` as the first commit (fresh history, so old versions can't be dug out).
4. Do not publish the `projects` repository itself: it holds your other projects.
5. Delete `public-release/` from this branch afterwards so there are not two copies.

## Small changes to the real project
- `tools/make_public.py` (new), this file (new), and `tools/demo_server.py` now prints its address when it starts.
