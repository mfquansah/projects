// Library: the big search box, example searches, and recent recordings. Also a single collection's list.
import { h, api, plural, put } from "../util.js";
import { state, go } from "../core.js";
import { searchBox, noteRows, emptyLibrary } from "./common.js";
import { recordingList } from "./list.js";

function greeting(name = "", now = new Date()) {
  const hr = now.getHours();
  if (hr < 5) return name ? `Still up, ${name}?` : "Still up?";
  const hello = hr < 12 ? "Good morning" : hr < 17 ? "Good afternoon" : "Good evening";
  return name ? `${hello}, ${name}` : hello;
}

export async function library({ main }) {
  main.classList.add("flush");
  const home = state.home;
  const total = home?.total_notes ?? 0;
  const below = h("div", {});
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  let seq = 0, timer = null;

  // compact hero: a quiet band with a faint waveform, not a billboard
  const bars = Array.from({ length: 44 }, (_, i) => {
    const px = Math.round(30 + Math.abs(Math.sin(i * 0.41) * Math.cos(i * 0.13 + 0.5)) * 120 + (i % 7) * 4);
    return h("i", { style: `height:${px}px;opacity:${(0.4 + (i % 5) * 0.1).toFixed(2)}` });
  });
  const hero = h("section", { class: "hero", "aria-label": "Introduction" },
    h("div", { class: "hero-wave", "aria-hidden": "true" }, bars),
    h("div", { class: "inner" },
      h("div", { class: "eyebrow" }, `A personal archive · ${plural(total, "recording")}`),
      h("h1", {}, greeting(state.settings?.name || "")),
      h("p", {}, "Voice notes, tagged, transcribed, and searchable.")));

  const tries = (home?.try || []).map((q) => h("a", { href: `#/search?q=${encodeURIComponent(q)}` }, `${q} ↗`));
  const box = searchBox({
    onInput: (v) => {
      clearTimeout(timer);
      const q = v.trim();
      if (!q) { ++seq; status.textContent = ""; showHome(); return; }
      timer = setTimeout(() => instant(q), 250);
    },
    onSubmit: (q) => { if (q) go(`#/search?q=${encodeURIComponent(q)}`); },
  });

  main.append(hero,
    h("div", { class: "col page overlap" }, box.el,
      tries.length ? h("div", { class: "tryline" }, h("span", { class: "eyebrow" }, "Try"), tries) : null, status),
    h("div", { class: "col page block", style: "margin-top:40px" }, below));

  // the four biggest collections as cards (every collection is also in the sidebar)
  function cards() {
    const top = (state.home?.categories || []).filter((c) => c.id !== null && c.count > 0).sort((a, b) => b.count - a.count).slice(0, 4);
    if (!top.length) return null;
    return h("section", { "aria-label": "Collections", style: "margin-bottom:52px" },
      h("h2", { class: "eyebrow ul", style: "margin-bottom:18px" }, "Collections"),
      h("div", { class: "cards" }, top.map((c, i) => h("a", { href: `#/collection/${c.id}` },
        h("span", { class: "n" }, String(i + 1).padStart(2, "0")), h("span", { class: "t" }, c.name), h("span", { class: "s" }, plural(c.count, "recording"))))));
  }

  async function showHome() {
    const r = await api("/api/browse?limit=8");
    if (total === 0) { put(below, emptyLibrary()); return; }
    put(below, cards(), h("section", { "aria-label": "Recent recordings" },
      h("div", { style: "display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding-bottom:4px" },
        h("h2", { class: "eyebrow ul" }, "Recent"), h("span", { class: "small" }, plural(total, "recording"), " · ", h("a", { class: "link", href: "#/all" }, "See all"))),
      noteRows(r.hits, "Nothing here yet.")));
  }
  async function instant(q) {
    const my = ++seq;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}&limit=8`);
      if (my !== seq) return;
      put(below, h("div", { style: "display:flex;align-items:baseline;justify-content:space-between;gap:12px;padding-bottom:4px" },
        h("h2", { class: "eyebrow ul" }, "Instant results"), h("span", { class: "small" }, "Press Enter for a full answer")),
        noteRows(r.hits, "No instant matches. Press Enter to ask the full question."));
    } catch (err) { status.textContent = err.message; }
  }
  await showHome();
}

export async function collection({ main, params }) {
  const id = params[0];
  const cat = (state.home?.categories || []).find((c) => (c.id === null ? "none" : String(c.id)) === id);
  return recordingList({ main, title: cat ? cat.name : "Collection", colId: id, back: { href: "#/", text: "← Library" } });
}
