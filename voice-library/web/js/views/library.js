// Library: the big search box, example searches, and recent recordings. Also a single collection's list.
import { h, api, plural } from "../util.js";
import { state, go } from "../core.js";
import { searchBox, noteRows, emptyLibrary } from "./common.js";

export async function library({ main }) {
  const home = state.home;
  const list = h("div", {});
  const heading = h("h1", { class: "eyebrow" }, "");
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  let seq = 0, timer = null;

  const tries = (home?.try || []).map((q) => h("a", { href: `#/search?q=${encodeURIComponent(q)}` }, q));
  const box = searchBox({
    onInput: (v) => {
      clearTimeout(timer);
      const q = v.trim();
      if (!q) { ++seq; status.textContent = ""; showRecent(); return; }
      timer = setTimeout(() => instant(q), 250);
    },
    onSubmit: (q) => { if (q) go(`#/search?q=${encodeURIComponent(q)}`); },
  });

  main.append(h("div", { class: "col" },
    box.el,
    tries.length ? h("div", { class: "tryline" }, h("span", {}, "Try"), tries) : null,
    h("div", { class: "sechead" }, heading),
    status, list));

  async function showRecent() {
    heading.textContent = `Recent · ${plural(state.home?.total_notes ?? 0, "recording")}`;
    const r = await api("/api/browse?limit=8");
    list.replaceChildren((state.home?.total_notes ?? 0) === 0 ? emptyLibrary() : noteRows(r.hits, "Nothing here yet."));
  }
  async function instant(q) {
    const my = ++seq;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}&limit=8`);
      if (my !== seq) return;
      heading.textContent = "Instant results · press Enter for a full answer";
      list.replaceChildren(noteRows(r.hits, "No instant matches. Press Enter to ask the full question."));
    } catch (err) { status.textContent = err.message; }
  }
  await showRecent();
}

export async function collection({ main, params }) {
  const id = params[0];
  const cat = (state.home?.categories || []).find((c) => (c.id === null ? "none" : String(c.id)) === id);
  const r = await api(id === "none" ? "/api/browse?uncategorized=true&limit=100" : `/api/browse?category_id=${encodeURIComponent(id)}&limit=100`);
  main.append(h("div", { class: "col" },
    h("a", { class: "back", href: "#/" }, "← Library"),
    h("h1", { class: "h1", style: "margin-top:8px" }, cat ? cat.name : "Collection"),
    h("p", { class: "muted", style: "margin:0 0 12px" }, plural(r.hits.length, "recording")),
    noteRows(r.hits, "Nothing in this collection yet.")));
}
