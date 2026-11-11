# Design mockups (reference only, not production code)

- `MainGreen.dc.html`: chosen home layout, forest green palette (see CLAUDE.md "Design (decided)").
- `AltPortal.dc.html`: alternative left-tab portal layout, already in the green palette.
- `Ask.dc.html`, `Flood.dc.html`: still on the earlier blue/black-header palette; apply the green palette when rebuilding.

Notes
- They reference `./support.js` (the design-canvas runtime) and `Main.dc.html`, neither of which is in this repo,
  so they will not render standalone. `MainGreen.dc.html` stands in for `Main.dc.html`.
- All numbers are layout placeholders. In particular 4,968 MW capacity and the 16% reserve margin are
  unverified (see CLAUDE.md "Known discrepancies"). Every number on the live site must come from the API.
