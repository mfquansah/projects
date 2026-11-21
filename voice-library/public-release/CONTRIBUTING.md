# Contributing

Thanks for wanting to help. This is a small personal project, so keep changes small and easy to review.

## Set up

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                      # the tests use stand-ins for Whisper, Claude and the models; no downloads or keys needed
python tools/demo_server.py    # a made-up library to click around in (no recordings, no key)
```

## Privacy rules (please read)

This app is built for private audio. When you open an issue or a pull request:

- **Never attach or paste real recordings, transcripts, titles, summaries or screenshots of your own library.** Use the demo
  library (`tools/demo_server.py`) or invented text.
- **Never paste an API key.** If one leaks, delete it in your provider's console and make a new one.
- Don't add code that sends **audio** anywhere. The design rule is that audio stays on the user's computer and only text
  goes to the language model.

## Good first ideas

See "Wish list" in the README. Making transcription faster, a settings screen, a share/export button, and better
sound-detection thresholds are all welcome.

## Before you open a pull request

- `pytest -q` passes, and new behaviour has a test.
- If you changed the page, run `node tools/e2e.js` (needs `npm i playwright`): it drives every screen in a real browser.
- Describe what you changed and why, in plain language.
