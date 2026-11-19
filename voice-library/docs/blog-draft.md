# I wanted to search my voice memos the way I search my photos

*Working title. Draft 1, written from your dictation of 2026-11-19. Things in [brackets] are for you to fill in or check.*

I have two little kids, and like a lot of parents I want to capture every moment. We take a lot of pictures, and I record audio too: when they're sleeping, when they first start making gurgle sounds, when one of them is singing before bed. When I have a memory, or I see something I want to keep, I record it. I use Voice Memos all the time.

But there's a huge gap in Apple's Voice Memos: you can't search it by what's in the audio. Apple has put AI under the Photos library, so you can search by context and it pulls out the right pictures. I love that. Nothing like it exists for audio.

So after recording my son singing at 2am, and then a week and 10 or 12 recordings later, I'm stuck when I want to find that one clip and show it to a friend or share it. With a photo you can see the context. With an audio recording you can't.

That started me down this path: **how can I make a voice library that's easy to categorize and search, so I can find a recording and share or export it?** I used AI to build it.

## Where it is now

The short version: I have a fairly functional app. It imports my recordings from Voice Memos on my Mac, and I can search my whole library in plain language. As it imports each recording, it gives it a title, writes a short summary and sorts it into collections like Ideas, Family memories and Work. It can also listen for sounds, like a baby laughing or crying, even when nobody is speaking. [Add the number of recordings imported so far, and one demo screenshot.]

## How I used AI

I came at this with a product management slant. I started with a recording of my own idea, then worked through three layers: the **UI**, the **engine underneath**, and the **development**.

The design began on paper, because I still love paper. I took the sketches to ChatGPT for the first architecture drawings and wireframes. [Add the wireframe images.] Then I moved to Claude Design for mockups and to Claude Code for the build.

The part that made this really cool: while building, I created a skill called **build trail**. It records the process as we go (every decision, why we made it, and what's still a guess) and then generates a product brief from that record. So I can look back at not just what the app does, but why it does it that way. [Link to the decision log or the build-trail page.]

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

## What's next

- **Error analysis and evals.** I need to check that the AI is giving the right output, using recordings where I know the answer.
- **Making sync automatic.** Right now I import from Voice Memos on my Mac. I'm working on getting it to run by itself.
- **The phone.** Nobody really wants this only on a desktop. As far as I can tell, Apple doesn't give apps a simple way to pull Voice Memos off the phone, so I need an approved way to sync that ends up on a mobile app. [Confirm the wording on Apple's limits before publishing.]

---

### Notes for you
- I read "my con's singling" as "my son's singing". Correct me if that's wrong.
- You said you'd explain the sound confidence part as "probabilistic". I used "confidence score" instead, since that's plainer. Say if you want the word back.
- Everything here comes from your own words and the project's records. I included no real recording titles, names or file paths.
- Missing pieces: screenshots (use the demo library only), the recording count, and the final result of the baby-giggle search.
