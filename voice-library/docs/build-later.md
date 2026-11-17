# Build later (shelf)

Things we decided to do, but not now. Each says why it's on the shelf and how to bring it back. Unverified or guessed items live in `revisit.md`; this file is for features.
Updated 2026-11-17.

## Shelved on purpose
- **"Keep in sync with Voice Memos" switch on the Import screen.** Built and tested (backend, API, sidebar status line), but the switch is hidden (`SHOW_SYNC_PANEL = false` in `web/js/views/import.js`) because it needs the macOS Full Disk Access permission first, which the user is turning on by hand, and syncing isn't what's being tested right now. The sync can still be driven through `POST /api/sync/settings` and `/api/sync/run`. To bring it back: set the flag to `true` (the sidebar status line already reappears when sync is on).
- **A link that opens macOS System Settings at Full Disk Access.** An app cannot grant itself that permission; at most it can open the right settings pane (a `x-apple.systempreferences:` link) and explain what to switch on. Nice-to-have for the "macOS is blocking access" message.
- **Start at login.** Needs a launch agent and a safe place for the Claude API key (macOS Keychain, not a plain file).
- **Long-import comforts.** A live time estimate while it runs, pause/resume/cancel, and a queue that survives an app restart.
- **Phone web app** reaching the library through the Mac (login, private connection, installable web app). Agreed direction, after the large import.
- **Native phone app with recording in the app, and a cloud copy of the library.** Later; a cloud copy puts recordings on someone else's servers, so decide deliberately.
- **Carrying the ivory/slate look onto the remaining mockups** (Search, Recording, Import) on the design canvas.
