// Needs attention: suggested collections, notes worth a second look, tags to promote, and archived notes.
import { h, api, fmtDate, fmtDur, plural, toast, put } from "../util.js";
import { refreshHome, collectionDialog } from "../core.js";

export async function attention({ main }) {
  const box = h("div", { class: "col", style: "gap:8px" });
  main.append(box);
  await load();

  async function load() {
    const d = await api("/api/attention");
    const act = (fn, msg) => async () => { try { await fn(); await refreshHome(); if (msg) toast(msg); await load(); } catch (err) { toast(err.message); } };
    const section = (title, ...kids) => h("section", { style: "margin-top:28px" }, h("h2", { class: "eyebrow", style: "padding:0 4px 8px" }, title), kids);
    const empty = !d.suggestions.length && !d.review.length;
    put(box,
      h("div", { style: "display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:12px" },
        h("h1", { class: "h1" }, "Needs attention"),
        h("button", { type: "button", class: "link", onclick: () => collectionDialog({ onDone: load }) }, "+ New collection")),
      h("p", { class: "muted", style: "margin:0" }, "Nothing here is ever deleted. Archiving only hides a recording, and you can restore it below."),
      empty ? h("div", { class: "empty" }, "Nothing needs your attention right now.") : null,
      d.suggestions.length ? section("Suggested collections", d.suggestions.map((s) => h("div", { class: "card" },
        h("div", { class: "l" }, h("strong", {}, s.name), h("span", { class: "muted" }, `  ·  ${plural(s.count, "recording")}`)),
        h("div", { class: "actions" },
          h("button", { type: "button", class: "primary", style: "padding:6px 14px", onclick: act(() => api("/api/suggestions/accept", { body: { name: s.name } }), `Created “${s.name}”.`) }, "Accept"),
          h("button", { type: "button", class: "ghost", onclick: act(() => api("/api/suggestions/reject", { body: { name: s.name } })) }, "Dismiss"))))) : null,
      d.review.length ? section("Worth a second look", d.review.map((n) => h("div", { class: "card" },
        h("div", { class: "l" }, h("a", { href: `#/note/${n.id}`, style: "font-weight:500" }, n.title),
          h("div", { class: "muted", style: "font-size:14px" }, n.summary),
          h("div", { class: "small" }, [fmtDate(n.recorded_at, { year: true }), n.duration_s ? fmtDur(n.duration_s) : null].filter(Boolean).join(" · "))),
        h("div", { class: "actions" },
          h("button", { type: "button", class: "ghost", onclick: act(() => api(`/api/notes/${n.id}/flag`, { body: { flag: "keep" } }), "Kept.") }, "Keep"),
          h("button", { type: "button", class: "ghost", onclick: act(() => api(`/api/notes/${n.id}/flag`, { body: { flag: "archived" } }), "Archived.") }, "Archive"))))) : null,
      d.tags.length ? section("Turn a tag into a collection", h("div", { class: "chips" }, d.tags.map((t) => h("button", { type: "button", title: "Create a collection from this tag", onclick: () => collectionDialog({ fromTag: t.tag, onDone: load }) }, `${t.tag} · ${t.count}`)))) : null,
      d.archived.length ? section("Archived", d.archived.map((n) => h("div", { class: "card" },
        h("div", { class: "l" }, h("a", { href: `#/note/${n.id}` }, n.title), h("div", { class: "small" }, fmtDate(n.recorded_at, { year: true }))),
        h("button", { type: "button", class: "ghost", onclick: act(() => api(`/api/notes/${n.id}/flag`, { body: { flag: null } }), "Restored.") }, "Restore")))) : null);
  }
}
