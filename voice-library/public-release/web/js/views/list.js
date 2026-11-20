// A list of recordings you can sort, filter and select from. Used by "All recordings" and by every collection.
// (Search results are a different screen on purpose: there is no select or bulk delete there.)
import { h, api, plural, toast, fmtDate } from "../util.js";
import { state, go, refreshHome } from "../core.js";
import { playButton, lengthText } from "./common.js";

const PAGE = 50;
const prefs = { sort: "newest" };   // the chosen sort is remembered while the app stays open

const SORTS = [["newest", "Newest first"], ["oldest", "Oldest first"], ["longest", "Longest first"], ["shortest", "Shortest first"], ["title", "Title A to Z"]];
const DATES = [["any", "Any time"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["year", "This year"], ["custom", "Custom range…"]];
const LENGTHS = [["any", "Any length"], ["u1", "Under 1 minute"], ["1to10", "1 to 10 minutes"], ["10to45", "10 to 45 minutes"], ["o45", "Over 45 minutes"]];
const LEN_RANGE = { u1: [null, 60], "1to10": [60, 600], "10to45": [600, 2700], o45: [2700, null] };

const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return iso(d); };

export async function allRecordings({ main }) {
  return recordingList({ main, title: "All recordings", colId: null });
}

// colId: null = every recording (with a collection filter), "none" = uncategorized, otherwise a collection id.
export function recordingList({ main, title, colId, back }) {
  const f = { cat: "", date: "any", from: "", to: "", len: "any", tag: "" };
  let hits = [], total = 0, selecting = false, seq = 0, modal = null, offset = 0;
  const sel = new Set();

  // ---------- controls (built once) ----------
  const field = (label, control) => h("label", { class: "fld" }, h("span", {}, label), control);
  const select = (options, value, onchange) => {
    const el = h("select", { onchange: (e) => onchange(e.target.value) }, options.map(([v, t]) => h("option", { value: v }, t)));
    el.value = value;
    return el;
  };
  const sortEl = select(SORTS, prefs.sort, (v) => { prefs.sort = v; load(true); });
  const cats = (state.home?.categories || []).filter((c) => c.count > 0 || c.id !== null);
  const catEl = select([["", "All collections"], ...cats.map((c) => [c.id === null ? "none" : String(c.id), c.name])], "", (v) => { f.cat = v; load(true); });
  const dateEl = select(DATES, "any", (v) => { f.date = v; customBox.hidden = v !== "custom"; load(true); });
  const lenEl = select(LENGTHS, "any", (v) => { f.len = v; load(true); });
  const tagEl = select([["", "Any tag"]], "", (v) => { f.tag = v; load(true); });
  const fromEl = h("input", { type: "date", "aria-label": "From date", onchange: (e) => { f.from = e.target.value; load(true); } });
  const toEl = h("input", { type: "date", "aria-label": "To date", onchange: (e) => { f.to = e.target.value; load(true); } });
  const customBox = h("div", { class: "fld custom", hidden: true }, h("span", {}, "Between"), fromEl, h("span", {}, "and"), toEl);
  const clearBtn = h("button", { type: "button", class: "linkbtn", hidden: true, onclick: () => {
    Object.assign(f, { cat: "", date: "any", from: "", to: "", len: "any", tag: "" });
    catEl.value = ""; dateEl.value = "any"; lenEl.value = "any"; tagEl.value = ""; fromEl.value = ""; toEl.value = ""; customBox.hidden = true;
    load(true);
  } }, "Clear filters");
  const selectBtn = h("button", { type: "button", class: "ghost", "aria-pressed": "false", onclick: () => setSelecting(!selecting) }, "Select");
  const count = h("p", { class: "muted", style: "margin:0", role: "status" });
  const rowsBox = h("div", {});
  const moreBtn = h("button", { type: "button", class: "ghost", hidden: true, onclick: () => load(false) });
  const bar = h("div", { class: "bulkbar", role: "region", "aria-label": "Selected recordings", hidden: true });

  const controls = h("div", { class: "listbar" },
    field("Sort", sortEl), colId === null ? field("Collection", catEl) : null, field("Date", dateEl), field("Length", lenEl), field("Tag", tagEl),
    customBox, clearBtn);

  const root = h("div", { class: "col" },
    back ? h("a", { class: "back", href: back.href }, back.text) : null,
    h("div", { style: "display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:8px" },
      h("h1", { class: "h1", style: "margin:0" }, title), selectBtn),
    h("div", { style: "margin:6px 0 14px" }, count), controls, rowsBox,
    h("div", { style: "margin:18px 0 90px;display:flex;justify-content:center" }, moreBtn), bar);
  main.append(root);

  // ---------- data ----------
  function query(off) {
    const p = new URLSearchParams({ sort: prefs.sort, limit: String(PAGE), offset: String(off) });
    if (colId === "none" || (colId === null && f.cat === "none")) p.set("uncategorized", "true");
    else if (colId !== null) p.set("category_id", colId);
    else if (f.cat) p.set("category_id", f.cat);
    if (f.date === "7") p.set("since", daysAgo(7));
    else if (f.date === "30") p.set("since", daysAgo(30));
    else if (f.date === "year") p.set("since", `${new Date().getFullYear()}-01-01`);
    else if (f.date === "custom") { if (f.from) p.set("since", f.from); if (f.to) p.set("until", f.to); }
    if (f.len !== "any") { const [lo, hi] = LEN_RANGE[f.len]; if (lo !== null) p.set("min_length", String(lo)); if (hi !== null) p.set("max_length", String(hi)); }
    if (f.tag) p.set("tag", f.tag);
    return p.toString();
  }
  const filtered = () => f.cat !== "" || f.date !== "any" || f.len !== "any" || f.tag !== "";

  async function load(reset) {
    const my = ++seq;
    if (reset) { offset = 0; sel.clear(); }
    try {
      const r = await api(`/api/browse?${query(reset ? 0 : hits.length)}`);
      if (my !== seq) return;   // a newer request has replaced this one
      hits = reset ? r.hits : hits.concat(r.hits);
      total = r.total;
    } catch (err) { if (my === seq) count.textContent = err.message; return; }
    clearBtn.hidden = !filtered();
    draw();
  }

  // ---------- drawing ----------
  function draw() {
    count.textContent = !total ? "No recordings" : hits.length < total ? `${hits.length} of ${plural(total, "recording")}` : plural(total, "recording");
    if (!hits.length) {
      rowsBox.replaceChildren(h("div", { class: "empty" }, filtered() ? "No recordings match these filters. " : (colId === null ? "Nothing here yet. " : "Nothing in this collection yet. "),
        filtered() ? h("button", { type: "button", class: "linkbtn", onclick: () => clearBtn.click() }, "Clear filters") : null));
    } else rowsBox.replaceChildren(...hits.map(row));
    const left = total - hits.length;
    moreBtn.hidden = left <= 0;
    moreBtn.textContent = `Show ${Math.min(PAGE, left)} more`;
    drawBar();
  }

  function row(x, i) {
    const cb = h("input", { type: "checkbox", class: "pick", "aria-label": `Select ${x.title}` });
    cb.checked = sel.has(x.id);
    cb.addEventListener("change", () => pick(x.id, cb.checked, el));
    const el = h("div", { class: `row${sel.has(x.id) ? " picked" : ""}` },
      selecting ? cb : h("span", { class: "num" }, String(i + 1).padStart(2, "0")),
      playButton(x.id),
      h("a", { class: "rowbody", href: `#/note/${x.id}` }, h("span", { class: "t" }, x.title), h("span", { class: "s" }, x.summary)),
      h("div", { class: "rowmeta" }, h("span", { class: "cat" }, x.category || "Uncategorized"),
        h("span", {}, [fmtDate(x.recorded_at), lengthText(x)].filter(Boolean).join(" · "))));
    el.addEventListener("click", (e) => {
      if (!selecting || e.target === cb || e.target.closest(".playbtn")) return;
      e.preventDefault();
      cb.checked = !cb.checked;
      pick(x.id, cb.checked, el);
    });
    return el;
  }

  function pick(id, on, el) {
    if (on) sel.add(id); else sel.delete(id);
    el.classList.toggle("picked", on);
    drawBar();
  }

  function setSelecting(on) {
    selecting = on;
    if (!on) sel.clear();
    selectBtn.textContent = on ? "Done" : "Select";
    selectBtn.setAttribute("aria-pressed", String(on));
    draw();
  }

  function drawBar() {
    bar.hidden = !selecting;
    if (!selecting) return;
    const n = sel.size, none = n === 0;
    bar.replaceChildren(
      h("span", { class: "bulkcount", role: "status" }, none ? "Nothing selected" : `${n} selected`),
      h("button", { type: "button", class: "linkbtn", onclick: () => { hits.forEach((x) => sel.add(x.id)); draw(); } }, `Select all ${hits.length} shown`),
      h("span", { class: "grow" }),
      h("button", { type: "button", class: "ghost", disabled: none, onclick: () => act("archive") }, "Archive"),
      h("button", { type: "button", class: "ghost danger", disabled: none, onclick: confirmDelete }, "Delete permanently…"),
      h("button", { type: "button", class: "ghost", onclick: () => setSelecting(false) }, "Done"));
  }

  // ---------- actions ----------
  async function act(action) {
    const ids = [...sel];
    try {
      const r = await api("/api/notes/bulk", { body: { action, ids } });
      const word = action === "archive" ? "Archived" : "Deleted";
      toast(r.failed.length ? `${word} ${plural(r.done, "recording")}; ${r.failed.length} couldn't be processed.`
        : action === "archive" ? `Archived ${plural(r.done, "recording")}. You can restore them from Needs attention.` : `Deleted ${plural(r.done, "recording")}.`);
    } catch (err) { toast(err.message); return; }
    sel.clear();
    await refreshHome();
    await load(true);
  }

  function closeModal() {
    if (!modal) return;
    document.removeEventListener("keydown", modal.onKey);
    modal.el.remove();
    const back = modal.opener;
    modal = null;
    if (back && back.isConnected) back.focus();
  }

  function confirmDelete(ev) {
    if (modal || !sel.size) return;
    const n = sel.size, opener = ev.currentTarget;
    const yes = h("button", { type: "button", class: "ghost danger solid", onclick: async () => { closeModal(); await act("delete"); } }, `Yes, delete ${plural(n, "recording")}`);
    const no = h("button", { type: "button", class: "ghost", onclick: closeModal }, "Cancel");
    const card = h("section", { class: "share-card", role: "alertdialog", "aria-modal": "true", "aria-labelledby": "bd-title" },
      h("h2", { id: "bd-title", style: "margin:0;font:600 20px/1.2 Sora, system-ui, sans-serif" }, `Delete ${plural(n, "recording")} for good?`),
      h("p", { class: "muted", style: "margin:0" },
        "This removes each recording's transcript, title, summary and this app's copy of the audio. Your originals in Voice Memos are not touched, and these recordings will not be imported again. It can't be undone."),
      h("div", { style: "display:flex;gap:10px;flex-wrap:wrap" }, yes, no));
    const backdrop = h("div", { class: "modal-backdrop", onclick: (e) => { if (e.target === backdrop) closeModal(); } }, card);
    const onKey = (e) => {
      if (e.key === "Escape") closeModal();
      else if (e.key === "Tab") { e.preventDefault(); (document.activeElement === yes ? no : yes).focus(); }
    };
    document.addEventListener("keydown", onKey);
    modal = { el: backdrop, onKey, opener };
    document.body.appendChild(backdrop);
    no.focus();   // the safe choice has the focus
  }

  // ---------- start ----------
  api("/api/tags").then((r) => {
    for (const t of r.tags) tagEl.append(h("option", { value: t.tag }, `${t.tag} (${t.count})`));
    tagEl.value = f.tag;
  }).catch(() => { /* the tag filter just stays empty */ });
  load(true);
  return () => { seq++; closeModal(); };
}
