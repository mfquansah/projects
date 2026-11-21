# I wanted to search my voice memos the way I search my photos

*Draft 2, 2026-11-21. Written from your own words, the decision log and this build. Things in [brackets] are for you to fill in or check. Use demo-library screenshots only.*

I have two little kids, and like a lot of parents I want to capture every moment. We take plenty of pictures, and I record audio too: when they're asleep, when they first make gurgling sounds, when one of them is singing before bed. When I have a thought I don't want to lose, I record that too. I use Voice Memos all the time.

There's a big gap in Apple's Voice Memos, though: you can't search it by what's *in* the audio. Apple's Photos app lets me type "dog on the beach" and finds the picture, and I never tagged it. Nothing like that exists for audio. So a week and a dozen recordings after my son sang at 2am, I'm stuck. With a photo you can see the context. With a recording you can't.

That started me down this road: **how can I build a voice library that's easy to search, so I can find a recording and share or export it?** I used AI to build it. I call it **Kasa Adaka**, which is Twi for roughly "talk box".

## The idea I borrowed from photos

I'm no expert on how Apple does it, but as I understand it, the trick is metadata: a hidden layer of description attached to every image, built quietly in the background by machine learning. By the time you search, the work is already done. [Add a source for this.]

I wanted that for audio. The moment a recording comes in, the app gets to work. It turns the speech into text. Claude reads the text and gives the recording a title, a short summary, a few tags and a home in a collection. A sound model listens for things like a baby laughing, even when nobody is speaking. I never tag anything. Because the heavy lifting happens once, up front, searching is fast.

## What it does today

- **Imports** my recordings straight from Voice Memos on my Mac. [Add the number imported so far.]
- **Understands** each one: title, summary, tags and a collection (Ideas, Family memories, Work & projects, Personal reflections, Other). Claude can suggest new collections, but nothing changes until I accept.
- **Searches in plain language**: "the recording of my baby laughing", "my longest note about work". It combines exact-word search with search by meaning, then labels each result as a clear match, a partial match or only related, and says why.
- **Browses everything** on an All recordings page: sort by newest, oldest, longest, shortest or A to Z, filter by collection, date, length or tag, and select several recordings to archive or delete in one go.
- **Plays and reads** each recording: a waveform with markers where it heard a baby laugh, a transcript that highlights the line being spoken, and a click on any line to jump there.
- **Shares** a recording: one click opens an email draft in Mail with the audio attached, or I can download the file under a readable name. I review the draft and press Send myself; the app never sends anything.

[Add 3 demo screenshots: the Library, a search result, a recording page.]

## How I worked with AI

I came at this as a product person. I started with a recording of my own idea and worked through three layers: the **UI**, the **engine underneath**, and the **development**.

The design began on paper, because I still love paper. I took the sketches to ChatGPT for first architecture drawings and wireframes [add the wireframes], then used Claude Design for mockups and Claude Code to build.

While building, I made a skill called **build trail**. It records the process as we go: every decision, why we made it, and what's still a guess. Then it generates a product brief from that record. That means I can look back at not just what the app does, but *why*. Two files do most of the work: `revisit.md` holds guesses and things I haven't verified, and `build-later.md` holds features I chose to put on the shelf. They do different jobs, so they're different files. [Link to the decision log.]

A few habits emerged, and I'd call them that rather than a method:
1. **Recommend, then ask.** I got a recommended option first and made the call. Sometimes I overrode it.
2. **Write the tradeoff down.** Decision, alternatives, why, and whether it's easy to undo.
3. **Prefer what can be undone.** Archive before delete. Sync is opt-in. Imports never touch the originals.
4. **Measure before committing.** A timed test batch came before the big import.
5. **Say what's unverified.** Out loud, in a file.

## Privacy was the first decision

These are my kids' voices. So **audio and transcription stay on my Mac, and only text goes to Claude.** That cost me speed, because cloud transcription is faster, and I decided it was worth it.

| Job | What does it | Where it runs |
|---|---|---|
| Speech to text | Whisper (faster-whisper, "small") | My Mac |
| Titles, summaries, understanding my questions | Claude | The cloud, but only ever the text |
| Finding by meaning | A small embedding model | My Mac |
| Finding by exact words | SQLite full-text search | My Mac |
| Hearing a baby laugh or cry | An audio classifier trained on Google's AudioSet | My Mac |
| The app itself | Python and FastAPI behind a plain web page | My Mac, local only |

## The real world pushed back

- **Getting the audio out.** I assumed I could drag recordings out of Voice Memos. Dragging hands a browser a "promise" of a file, not a file. And macOS blocks apps from reading the Voice Memos folder until you grant Full Disk Access and fully restart Terminal. So the app now reads the library directly, with a clear message about the permission. That's also when I learned I have **505 recordings, not the 1,000 I'd guessed**.
- **Every date was wrong.** My first 19 imports all carried the date I exported them, not the date I recorded them. The fix: read the date from inside the audio file.
- **An update broke transcription.** A dependency update stopped it completely until we pinned the older version.
- **Tests passed on one machine and failed on the other.** That led straight to the date bug.

## Making it safe to press the button twice

With 500 recordings and an import that takes hours, one rule matters most: **I can press Import as often as I like and nothing bad happens.**

The app doesn't care what a file is called. It takes a **fingerprint of the audio itself**. Same sound, same fingerprint, same recording. That means:
- Pressing Import twice skips everything already there: nothing is transcribed again, nothing is sent to Claude again, and my edited titles stay as I left them.
- Stopping halfway is fine. The next run picks up only what's missing.
- "Import the next 100" means 100 *new* ones.

**Leaving things out on purpose.** I measured first. Of 499 recordings, 42 were longer than 45 minutes, adding up to almost 56 hours, mostly work meetings I didn't want in a family library, and nearly half the import time. So anything over 45 minutes is skipped, before it's copied, transcribed or sent anywhere, and I can change the limit.

**Deleting.** My first rule was *hide first, delete only when you're sure*: Archive can be undone. Later I added permanent delete, with a confirmation that says exactly what goes, and the app remembers what I deleted so it doesn't come back on the next import. My originals in Voice Memos are never touched.

**One honest catch.** If I trim a recording in Voice Memos after importing it, its audio changes, so it looks like a new recording. I'd rather have that than have the app quietly overwrite something I'd already organised.

## Designing it with Claude Design

This was the most fun part. I made mockups before any screen existed in code, and gave feedback one round at a time:
- The search box: taller, with the prompt ("Find a thought, recording or memory…") in a serif, upright and a little faint.
- The look: "it looks like a Claude app, and I don't want that." I pointed to a couple of sites I liked. A deep crimson was too strong. We landed on soft ivory with slate and charcoal accents, and softer corners, because I wanted it calming to look at.
- Later rounds, once the app worked: the All recordings page (filter chips with counts, year headings, rows with a play button, title, summary and length) and the recording page (cards, a transcript with the current line highlighted, icons in the sidebar). I kept my own colours and only copied the layout and icons.

[Add the first mockup and the final version side by side.]

Two lessons stuck:
- **Give the tool the source, not a picture of it.** I sent screenshots of a logo and Claude guessed the font wrong three times. When I pasted the actual HTML, the answer was right there: Sora, with exact sizes and colours. A screenshot shows what something looks like; the source says what it is.
- **Show the real thing again.** I once described a mockup instead of sharing it, and the result was a guess that missed. When I shared the picture, we matched it in one pass.

The logo itself: four bars of different heights, like a sound wave, inside a rounded outline, in green, gold and red. [Add the logo, and say whether the colours mean anything to you.]

## Testing, and understanding your tools

The sound model doesn't say "that's a baby laughing". It gives a confidence score from 0 to 1, so someone has to pick where to draw the line. Our first line was too strict and hid a faint giggle. We lowered it, and weaker matches now show as "possibly". [Check this against the real result once you've re-run the sound check.]

The project has over 260 automated tests, plus a test that drives the app in a real browser and fails on any error, stray text or sideways scrolling, including at phone width. Several of my best moments came from asking: "wait, what are we testing right now?" **When you build with AI tools, engage with how they work.**

## The problem right now: speed

I timed the test import: **25 recordings took about an hour**, roughly 2 minutes each. At that rate the rest is a long job. A timing tool I built shows about **90% of the time is transcription**; titling, indexing and sound detection are small by comparison. [Add the result of "Import the next 100" and the time breakdown.]

The best fix for how it *feels* is automatic syncing, so the app quietly picks up each new recording as I make it. A single new recording takes a couple of minutes, which nobody notices in the background. To be honest, that hides the wait; it doesn't shrink it. I'm also looking at making transcription itself faster (a quicker decoder, working in chunks, using the Mac's graphics chip). [Add which one you try and what it changed.]

**Where sync stands.** It's built and has passed its automated tests, and I've seen it work in a browser against a *demo* Voice Memos folder: it imported everything, picked up a new file, made no duplicates, and left originals untouched. But the switch is hidden in the app, and I haven't yet run it against my real Voice Memos. It only runs while the app is open, and I want a pause button first. [Update this once you've tried it.]

## What's next

- **Checking the AI.** Evals with recordings where I know the right answer, to measure how well search really works. (I don't remember my own notes, which is the reason for the project and also why this is hard.)
- **Sync on my real library**, running by itself.
- **A pause button** for long imports.
- **The phone.** Nobody wants this only on a desktop. As far as I can tell, Apple gives apps no simple way to pull Voice Memos off the phone, so I need an approved route that ends in a mobile app. [Confirm the wording on Apple's limits before publishing.]

## The wish list

- **A link you can send** without an email app.
- **A family library.** The kids' first sounds, a grandparent telling a story, a funny moment from a cousin, all searchable in one place. That's a much bigger step than a personal app, because other people's recordings would live somewhere shared, so privacy has to be designed in from the start. [Keep or cut that line.]
- **Open it up.** I'd like to put the code on GitHub so others can play with it and make it better. [Decide this once you've confirmed the licence.]

---

### Notes for you
- Facts I'm unsure of are in brackets. Numbers in the text come from the project's records: 505 recordings found, 42 of 499 over 45 minutes (about 56 hours), 25 recordings in about an hour, about 90% of time in transcription.
- I changed one thing from draft 1: it said sync was "built and tested". Sync is verified only against a demo folder, so the post now says so.
- No real recording titles, names or file paths are included. Use demo-library screenshots only.
- Cut or keep: the five habits list, the tech table, and the logo paragraph are the easiest things to drop if it runs long (it's about 1,900 words now).
