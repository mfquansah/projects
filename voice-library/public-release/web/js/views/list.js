// A list of recordings you can sort, filter and select from. Used by "All recordings" and by every collection.
// (Search results are a different screen on purpose: there is no select or bulk delete there.)
import { h, api, plural, toast, fmtDate } from "../util.js";
import { state, go, refreshHome } from "../core.js";
import { playButton, lengthText } from "./common.js";

const PAGE = 50;
const prefs = { sort: "newest" };   // the chosen sort is remembered while the app stays open

const SORTS = [["newest", "Newest first"], ["oldest", "Oldest first"], ["longest", "Longest first"], ["shortest", "Shortest first"], ["title", "Title A to Z"]];
const DATES = [["any", "Any time"], ["7", "Last 7 days"], ["30", "Last 30 days"], ["year", "This year"], ["custom", "Custom range…", null, "Custom range"]];
const LENGTHS = [["any", "Any length", null, "Any"], ["u1", "Under 1 minute", null, "Under 1 min"], ["1to10", "1 to 10 minutes", null, "1 to 10 min"], ["10to45", "10 to 45 minutes", null, "10 to 45 min"], ["o45", "Over 45 minutes", null, "Over 45 min"]];
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
  const SVG = (d, w = 18) => { const t = document.createElement("template"); t.innerHTML = `<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`; return t.content.firstChild; };
  const CHECK = () => SVG('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 16);
  const CHEV = () => SVG('<path d="M6 9l6 6 6-6"/>', 16);
  const cats = (state.home?.categories || []).filter((c) => c.count > 0 || c.id !== null);
  const libTotal = (state.home?.categories || []).reduce((n, c) => n + (c.count || 0), 0);
  const COLLS = [["", "All collections", null], ...cats.map((c) => [c.id === null ? "none" : String(c.id), c.name, c.count])];
  let tagOpts = [["", "Any", null]];
  let openMenu = null;

  function closeMenu(focus) {
    if (!openMenu) return;
    const { chip, menu } = openMenu;
    menu.remove(); chip.setAttribute("aria-expanded", "false");
    document.removeEventListener("mousedown", onOutside, true);
    openMenu = null;
    if (focus) chip.focus();
  }
  function onOutside(e) { if (openMenu && !openMenu.menu.contains(e.target) && !openMenu.chip.contains(e.target)) closeMenu(false); }

  // A filter chip: shows "label value" and opens a menu of choices (keyboard: arrows, Home/End, Enter, Escape).
  function chip({ label, options, get, set, wide, dflt, align }) {
    const valueEl = h("span", { class: "cv" });
    const btn = h("button", { type: "button", class: "chip", "aria-haspopup": "listbox", "aria-expanded": "false" },
      label ? h("span", { class: "cl" }, label) : null, valueEl, CHEV());
    const wrap = h("span", { class: `chipwrap${align === "right" ? " right" : ""}` }, btn);
    const sync = () => {
      const cur = options().find((o) => o[0] === get());
      valueEl.textContent = (cur && (cur[3] || cur[1])) || "";
      btn.classList.toggle("active", !!dflt && get() !== dflt);
    };
    function open() {
      if (openMenu && openMenu.chip === btn) return closeMenu(true);
      closeMenu(false);
      const opts = options();
      const items = opts.map(([v, t, n], i) => {
        const on = v === get();
        const it = h("button", { type: "button", role: "option", class: `mi${on ? " sel" : ""}`, "aria-selected": String(on), tabindex: "-1",
          onclick: () => { set(v); sync(); closeMenu(true); } },
          h("span", { class: "mc" }, on ? CHECK() : null), h("span", { class: "mt" }, t), n !== null && n !== undefined ? h("span", { class: "mn" }, String(n)) : null);
        return it;
      });
      const menu = h("div", { class: `menu${wide ? " wide" : ""}`, role: "listbox", "aria-label": label || "Sort" });
      items.forEach((it, i) => { menu.append(it); if (wide && i === 0 && opts.length > 1) menu.append(h("div", { class: "msep", role: "separator" })); });
      wrap.append(menu);
      btn.setAttribute("aria-expanded", "true");
      openMenu = { chip: btn, menu };
      document.addEventListener("mousedown", onOutside, true);
      (items.find((i) => i.classList.contains("sel")) || items[0]).focus();
      menu.addEventListener("keydown", (e) => {
        const i = items.indexOf(document.activeElement);
        const to = (n) => { e.preventDefault(); items[(n + items.length) % items.length].focus(); };
        if (e.key === "ArrowDown") to(i + 1); else if (e.key === "ArrowUp") to(i - 1);
        else if (e.key === "Home") to(0); else if (e.key === "End") to(items.length - 1);
        else if (e.key === "Escape") { e.preventDefault(); closeMenu(true); }
        else if (e.key === "Tab") closeMenu(false);
      });
    }
    btn.addEventListener("click", open);
    btn.addEventListener("keydown", (e) => { if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !openMenu) { e.preventDefault(); open(); } });
    sync();
    return Object.assign(wrap, { sync });
  }

  const sortChip = chip({ label: "Sort", options: () => SORTS.map(([v, t]) => [v, t, null, t.replace(" first", "").replace("Title A to Z", "A to Z")]), get: () => prefs.sort, set: (v) => { prefs.sort = v; load(true); }, align: "right" });
  const catChip = colId === null ? chip({ label: "", options: () => COLLS, get: () => f.cat, set: (v) => { f.cat = v; load(true); }, wide: true, dflt: "" }) : null;
  const dateChip = chip({ label: "", options: () => DATES, get: () => f.date, set: (v) => { f.date = v; customBox.hidden = v !== "custom"; load(true); }, dflt: "any" });
  const lenChip = chip({ label: "Length", options: () => LENGTHS, get: () => f.len, set: (v) => { f.len = v; load(true); }, dflt: "any" });
  const tagChip = chip({ label: "Tag", options: () => tagOpts, get: () => f.tag, set: (v) => { f.tag = v; load(true); }, dflt: "" });
  const fromEl = h("input", { type: "date", "aria-label": "From date", onchange: (e) => { f.from = e.target.value; load(true); } });
  const toEl = h("input", { type: "date", "aria-label": "To date", onchange: (e) => { f.to = e.target.value; load(true); } });
  const customBox = h("div", { class: "customrange", hidden: true }, h("span", {}, "Between"), fromEl, h("span", {}, "and"), toEl);
  const clearBtn = h("button", { type: "button", class: "linkbtn", hidden: true, onclick: () => {
    Object.assign(f, { cat: "", date: "any", from: "", to: "", len: "any", tag: "" });
    fromEl.value = ""; toEl.value = ""; customBox.hidden = true;
    [catChip, dateChip, lenChip, tagChip].forEach((c) => c && c.sync());
    load(true);
  } }, "Clear filters");
  const selectBtn = h("button", { type: "button", class: "chip selbtn", "aria-pressed": "false", onclick: () => setSelecting(!selecting) },
    SVG('<circle cx="12" cy="12" r="9"/><path d="M8 12.5l3 3 5-6"/>', 18), h("span", {}, "Select"));
  const count = h("p", { class: "subtitle", role: "status" });
  const rowsBox = h("div", {});
  const moreBtn = h("button", { type: "button", class: "ghost", hidden: true, onclick: () => load(false) });
  const bar = h("div", { class: "bulkbar", role: "region", "aria-label": "Selected recordings", hidden: true });

  const controls = h("div", { class: "chips" }, catChip, dateChip, lenChip, tagChip, clearBtn, sortChip);

  const root = h("div", { class: "col listpage" },
    back ? h("a", { class: "back", href: back.href }, back.text) : null,
    h("div", { class: "listhead" },
      h("div", {}, h("h1", { class: "listh1" }, title), count), selectBtn),
    controls, customBox, rowsBox,
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
  const SORT_WORDS = { newest: "newest first", oldest: "oldest first", longest: "longest first", shortest: "shortest first", title: "A to Z" };
  function draw() {
    const word = SORT_WORDS[prefs.sort];
    const all = colId === null ? libTotal : 0;
    count.textContent = !total ? "No recordings"
      : filtered() && all > total ? `${total} of ${plural(all, "recording")}, ${word}` : `${plural(total, "recording")}, ${word}`;
    if (!hits.length) {
      rowsBox.replaceChildren(h("div", { class: "empty" }, filtered() ? "No recordings match these filters. " : (colId === null ? "Nothing here yet. " : "Nothing in this collection yet. "),
        filtered() ? h("button", { type: "button", class: "linkbtn", onclick: () => clearBtn.click() }, "Clear filters") : null));
    } else {
      const byYear = prefs.sort === "newest" || prefs.sort === "oldest";
      const out = [];
      let cur = null, box = null;
      for (const x of hits) {
        if (byYear) {
          const y = x.recorded_at ? new Date(x.recorded_at).getFullYear() : "Date unknown";
          if (y !== cur) { cur = y; box = { y, items: [] }; out.push(box); }
          box.items.push(x);
        } else { if (!box) { box = { y: null, items: [] }; out.push(box); } box.items.push(x); }
      }
      rowsBox.replaceChildren(...out.map((g) => h("section", { class: "ygroup" },
        g.y !== null ? h("h2", { class: "yhead" }, h("span", {}, String(g.y)), h("span", { class: "yn" }, plural(g.items.length, "recording"))) : null,
        ...g.items.map(row))));
    }
    const left = total - hits.length;
    moreBtn.hidden = left <= 0;
    moreBtn.textContent = `Show ${Math.min(PAGE, left)} more`;
    drawBar();
  }

  function row(x) {
    const cb = h("input", { type: "checkbox", class: "pick", "aria-label": `Select ${x.title}` });
    cb.checked = sel.has(x.id);
    cb.addEventListener("change", () => pick(x.id, cb.checked, el));
    const len = lengthText(x);
    const el = h("div", { class: `lrow${sel.has(x.id) ? " picked" : ""}` },
      selecting ? cb : playButton(x.id),
      h("a", { class: "lbody", href: `#/note/${x.id}` }, h("span", { class: "lt" }, x.title), h("span", { class: "ls" }, x.summary)),
      h("span", { class: "lcat" }, x.category || "Uncategorized"),
      h("span", { class: "ldate" }, fmtDate(x.recorded_at)),
      h("span", { class: "llen" }, len || ""));
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
    selectBtn.lastChild.textContent = on ? "Done" : "Select";
    selectBtn.classList.toggle("active", on);
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
    tagOpts = [["", "Any", null], ...r.tags.map((t) => [t.tag, t.tag, t.count])];
  }).catch(() => { /* the tag filter just stays empty */ });
  load(true);
  return () => { seq++; closeMenu(false); closeModal(); };
}
