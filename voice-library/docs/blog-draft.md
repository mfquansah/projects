# I wanted to search my voice memos the way I search my photos

*Working title. Draft 1, written from your dictation of 2026-11-19. Things in [brackets] are for you to fill in or check.*

I have two little kids, and like a lot of parents I want to capture every moment. We take a lot of pictures, and I record audio too: when they're sleeping, when they first start making gurgle sounds, when one of them is singing before bed. When I have a memory, or I see something I want to keep, I record it. I use Voice Memos all the time.

But there's a huge gap in Apple's Voice Memos: you can't search it by what's in the audio. Apple has put AI under the Photos library, so you can search by context and it pulls out the right pictures. I love that. Nothing like it exists for audio.

So after recording my son singing at 2am, and then a week and 10 or 12 recordings later, I'm stuck when I want to find that one clip and show it to a friend or share it. With a photo you can see the context. With an audio recording you can't.

That started me down this path: **how can I make a voice library that's easy to categorize and search, so I can find a recording and share or export it?** I used AI to build it.

## Why photo search works, and how I borrowed it

Here's the thing that got me. I can type "dog on the beach" into Apple Photos and it finds the picture. I never tagged it. Nobody tags their photos; who has the time? I'm no expert on how Apple does it, but from what I've read, the secret is metadata: a hidden layer of description attached to every image. And Photos builds it for you, quietly, in the background, using machine learning to look at each picture and note what's in it. By the time you search, the work is already done. [Add the source for this idea.]

I wanted that for audio, so that's what I built. The moment a recording comes in, the app gets to work. It turns the speech into text. Claude reads that text and gives the recording a title, a summary and a home in a collection. A sound model listens for the good stuff, like a baby laughing. I never tag a thing. And because all the heavy lifting happens once, up front, searching is fast.

## Where it is now

The short version: I have a fairly functional app. It imports my recordings from Voice Memos on my Mac, and I can search my whole library in plain language. As it imports each recording, it gives it a title, writes a short summary and sorts it into collections like Ideas, Family memories and Work. It can also listen for sounds, like a baby laughing or crying, even when nobody is speaking. [Add the number of recordings imported so far, and one demo screenshot.]

## How I used AI

I came at this with a product management slant. I started with a recording of my own idea, then worked through three layers: the **UI**, the **engine underneath**, and the **development**.

The design began on paper, because I still love paper. I took the sketches to ChatGPT for the first architecture drawings and wireframes. [Add the wireframe images.] Then I moved to Claude Design for mockups and to Claude Code for the build.

The part that made this really cool: while building, I created a skill called **build trail**. It records the process as we go (every decision, why we made it, and what's still a guess) and then generates a product brief from that record. So I can look back at not just what the app does, but why it does it that way. [Link to the decision log or the build-trail page.]

## The steps

Here's the order I worked in. Each step had its own surprise.

**1. Figure out how to export the audio.** I assumed I could drag recordings out of Voice Memos and into the app. It doesn't work: dragging out of Voice Memos hands over a "promise" of a file, not a file, so a browser gets nothing. Then I found that macOS blocks apps from reading the Voice Memos folder unless you grant Full Disk Access, and Terminal has to be fully restarted for it to count. The fix was to have the app read the Mac's Voice Memos library directly, with a clear message that explains the permission. That's also when I learned I have **505 recordings, not the 1,000 I'd guessed**.

**2. Categorize the audio.** As each recording comes in, Claude reads the transcript and gives it a title, a short summary, a few tags and a collection. I started with five collections (Ideas, Family memories, Work & projects, Personal reflections and Other). Claude can suggest new ones, but nothing changes until I accept. There's also a review list for recordings that may be accidental, and a rule I set early: **archive, never delete.**

**3. Make it searchable.** I wanted to type the way I'd talk: "the recording of my baby laughing" or "my longest note about work". The app combines exact-word search with search by meaning, and Claude works out the question: the topic, the dates, "my longest". Then it labels each result as a clear match, a partial match or only related, and says why. Sounds are searchable too, even when nobody speaks.

**4. Importing issues.** This was where the real world pushed back:
- **Every date was wrong.** The first 19 imports all carried the date I exported them, not the date I recorded them. The fix was to read the date from inside the audio file itself.
- **Installs and updates broke things.** Downloads timed out on my Mac, and a dependency update stopped transcription completely until we pinned the older version.
- **It was slow.** 25 recordings took about an hour, and nearly all of that was transcription. So I measured first, with a test batch, before importing the rest.
- **Tests that passed on one machine failed on the other.** The tests ran fine in the cloud and failed on my Mac, which led to the date fix above.

## Designing it with Claude Design

This was the most fun part. Before any screen existed in code, I worked on mockups in Claude Design: the library, search, a single recording, and import. I brought my own earlier mockup, and we pushed it toward something more minimal. [Add the first mockup and the final version side by side.]

I gave a lot of feedback, one round at a time, and the design moved with it:
- **The search box:** make it taller, and put the prompt ("Find a thought, recording or memory…") in a serif font, upright and a little faint.
- **The look:** my first reaction was "it looks like a Claude app, and I don't want that." I pointed to a couple of sites I liked, including Harvard's. We tried a deep crimson, and it was too strong. We landed on soft ivory with slate and charcoal accents, and a background of `#F2F0EF`.
- **The layout:** keep the collections on the welcome screen and in the sidebar too.
- **The corners:** "quite sharp." I wanted the app to be beautiful and calming to look at, so everything got softer.

Then there was the logo. The name is **Kasa Adaka**, which is Twi for roughly "talk box" (*kasa*, speech, and *adaka*, box). The icon is four bars of different heights, like a sound wave, inside a rounded outline. I designed it in Claude Design, in green, gold and red. [Add the logo. Say here if the colours mean something to you.]

A small lesson from the logo: **give the tool the source, not a picture of it.** I sent screenshots, and Claude guessed at the font three times and got it wrong each time. When I pasted the actual HTML from the design file, the answer was right there: the font was Sora, with exact sizes and colours. A screenshot shows what something looks like, and the source says what it is.

## The tech stack, in plain language

| Job | What does it | Where it runs |
|---|---|---|
| Turn speech into text | **Whisper** (the faster-whisper version, "small" size) | On my Mac. The audio never leaves it. |
| Title, summary, category, and understanding my questions | **Claude** | In the cloud, but it only ever sees the text, never the audio |
| Find recordings by *meaning*, not just matching words | A small embedding model (MiniLM) | On my Mac |
| Find recordings by exact words | SQLite's built-in full-text search | On my Mac |
| Hear baby laughing, crying, babbling | An audio classifier trained on Google's AudioSet | On my Mac |
| The app itself | Python and FastAPI behind a plain web page | On my Mac, local only |

The design choice behind this table: **audio stays on my computer, and only text goes to Claude.** These are my kids' voices, so that mattered more to me than speed.

## Testing, and understanding your tools

Some of the testing had to get quite technical, especially for sounds. The sound model doesn't say "that's a baby laughing". It gives a confidence score between 0 and 1, so someone has to choose where to draw the line. Our first line was too strict and may have hidden a faint giggle, so we lowered it and now show weaker matches as "possibly". [Check this against the real result once you've re-run the sound check.]

The app also has 230 automated tests, plus a test that drives the app in a real browser and fails if it finds an error or stray text on screen.

One lesson stands out: **when you build with AI tools, engage with how they work.** Ask what each tool is doing and why. Several of my best moments were asking "wait, what are we testing right now?"

## The problem right now: importing takes forever

The biggest bottleneck is speed. I set a timer on the test import to record it: **25 recordings took about an hour**, roughly 2 minutes each. At that rate:

| Import | Recordings | Rough time |
|---|---|---|
| The test batch | 25 | about 1 hour (measured) |
| The next batch | 100 | about 4 hours |
| Everything left | about 480 | about 18 to 19 hours (an estimate) |

A tool I built to time each stage showed where the time goes: **about 90% is transcription**, turning speech into text. Titling, indexing and sound detection together are small by comparison. [Add the result of the next 100 and the time breakdown.]

So what's the answer? The best fix for how it *feels* is **automatic syncing in the background**. I don't want to import in batches and sit watching a progress bar. I want the app to quietly pick up each new recording from Voice Memos as I make it, and by the time I look for it, it's there. A single new recording takes a couple of minutes, which nobody notices in the background.

To be honest about it, sync doesn't make the work any faster. It hides the wait. Importing my 500 old recordings for the first time is still a long job, so I'm also looking at making transcription itself faster. The options I haven't tried yet are a quicker way of decoding the speech, processing it in chunks at the same time, and using the Mac's graphics chip. [Add which one you try and what it changed.]

## What's next

- **Error analysis and evals.** I need to check that the AI is giving the right output, using recordings where I know the answer.
- **Making sync automatic.** Right now I import from Voice Memos on my Mac and I choose when. The sync is built and tested, and the next step is getting it to run by itself in the background.
- **The phone.** Nobody really wants this only on a desktop. As far as I can tell, Apple doesn't give apps a simple way to pull Voice Memos off the phone, so I need an approved way to sync that ends up on a mobile app. [Confirm the wording on Apple's limits before publishing.]

## The wish list

Here's where I'd love to take it. Right now this is a personal app that lives on my Mac, and the things I dream about next are all about *sharing*:

- **Share a single recording.** The 2am singing clip is the reason I started. I want to find it and send it to a friend or a grandparent in two taps.
- **A family library.** Wouldn't it be cool if everyone in my family could load their voice notes into one shared library? The kids' first sounds, a grandparent telling a story, a funny moment from a cousin, all searchable in one place. Then we'd share them with each other.
- **On my phone.** Nobody really wants this only on a desktop.
- **Open it up.** I'd like to put the code on GitHub so other people can play with it, fork it and make it better. [Decide this once you've picked a licence.]

None of this is built yet, and a family library is a much bigger step than a personal app, because it means other people's recordings live somewhere shared, so privacy has to be designed in from the start. [Keep or cut that last line.]

---

### Notes for you
- I read "my con's singling" as "my son's singing". Correct me if that's wrong.
- You said you'd explain the sound confidence part as "probabilistic". I used "confidence score" instead, since that's plainer. Say if you want the word back.
- Everything here comes from your own words and the project's records. I included no real recording titles, names or file paths.
- Missing pieces: screenshots (use the demo library only), the recording count, and the final result of the baby-giggle search.
