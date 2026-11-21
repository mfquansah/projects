// Starts the app: sidebar, routing between screens, and the "Claude isn't connected" notice.
import { $, h, api, bus, shared, put, icons } from "./util.js";
import { state, refreshHome, refreshSync, ago } from "./core.js";
import { library, collection } from "./views/library.js";
import { allRecordings } from "./views/list.js";
import { search } from "./views/search.js";
import { note } from "./views/note.js";
import { importView } from "./views/import.js";
import { attention } from "./views/attention.js";

const routes = [
  [/^#\/?$/, "library", library],
  [/^#\/all$/, "all", allRecordings],
  [/^#\/collection\/(\w+)$/, "library", collection],
  [/^#\/search$/, "search", search],
  [/^#\/note\/(\d+)$/, "library", note],
  [/^#\/import$/, "import", importView],
  [/^#\/attention$/, "attention", attention],
];
let current = { name: "library", cleanup: null, colId: null };
const SIDE_COLLECTIONS = 5;   // the sidebar lists this many collections (the largest first); the rest sit behind "See more"
let sideExpanded = false;

function syncLine() {
  const sy = state.sync;
  if (!sy || !sy.available) return null;
  if (!sy.enabled) return null;   // the switch is shelved; nothing to point at while sync is off
  if (sy.problem) return h("a", { href: "#/import", class: "sync warn" }, "Sync paused. Tap for help.");
  const text = sy.pending > 0 ? `Syncing · ${sy.pending} importing` : (sy.last ? `Synced ${ago(sy.last.at)}${sy.last.new ? ` · ${sy.last.new} new` : ""}` : "Sync starting…");
  return h("div", { class: "sync" }, h("span", {}, text), " ",
    h("button", { type: "button", class: "link", onclick: async () => { try { await api("/api/sync/run", { method: "POST", body: {} }); } catch (_) { /* shown on refresh */ } refreshSync(); } }, "Sync now"));
}

// The Kasa Adaka logo, copied from the design file (icon 64x64, wordmark 116x76; the words are stretched to the same width).
const LOGO_SVG = `<svg class="logo-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Kasa Adaka">
<rect x="3" y="3" width="58" height="58" fill="none" rx="13" stroke="#26323C" stroke-width="3.5"/>
<rect x="14" y="23" width="6" height="18" fill="#1E8A5C" rx="3"/><rect x="24" y="13" width="6" height="38" fill="#EDB231" rx="3"/>
<rect x="34" y="16" width="6" height="32" fill="#D2432B" rx="3"/><rect x="44" y="26" width="6" height="12" fill="#EDB231" rx="3"/></svg>
<svg class="logo-word" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 116 76" aria-hidden="true">
<text x="0" y="36" textLength="116" lengthAdjust="spacing" font-family="'Sora', system-ui, sans-serif" font-weight="700" font-size="46" fill="#26323C">kasa</text>
<text x="0" y="76" textLength="116" lengthAdjust="spacing" font-family="'Sora', system-ui, sans-serif" font-weight="300" font-size="38" fill="#26323C">adaka</text></svg>`;

function brandLogo() {
  const el = h("a", { class: "brand", href: "#/", "aria-label": "Kasa Adaka, home" });
  el.innerHTML = LOGO_SVG;  // fixed markup above, no user data
  return el;
}

// A small picture for a collection, chosen from its name (a plain folder when nothing fits).
function collIcon(name) {
  const n = (name || "").toLowerCase();
  const pick = /idea/.test(n) ? icons.bulb : /family|memor|baby|kid/.test(n) ? icons.heart : /work|project|job/.test(n) ? icons.briefcase
    : /reflect|personal|journal|diary/.test(n) ? icons.book : /song|lullab|music/.test(n) ? icons.music : /other|misc/.test(n) ? icons.dots : icons.folder;
  return h("span", { class: "ico" }, pick(18));
}

const isOther = (c) => (c.name || "").trim().toLowerCase() === "other";

// The sidebar's collections: the biggest few, then "See more". A collection you are looking at is always shown.
function collectionsNav(home) {
  const all = (home?.categories || []).filter((c) => c.count > 0 || c.id !== null)
    .map((c) => ({ ...c, key: c.id === null ? "none" : String(c.id) }))
    .sort((a, b) => (isOther(a) - isOther(b)) || b.count - a.count || a.name.localeCompare(b.name));   // biggest first, "Other" always last
  // Collapsed: the biggest few, then "Other" (kept in view at the end); a collection you are looking at is always shown.
  const other = all.find(isOther);
  const head = all.filter((c) => c !== other).slice(0, other ? SIDE_COLLECTIONS - 1 : SIDE_COLLECTIONS);
  const picked = new Set([...head, ...(other ? [other] : [])]);
  const extra = all.filter((c) => !picked.has(c) && c.key === current.colId);
  const shown = sideExpanded ? all : all.filter((c) => picked.has(c) || extra.includes(c));
  const rest = all.filter((c) => !picked.has(c) && !extra.includes(c));   // the ones "See more" reveals
  return h("div", { class: "cols" }, h("p", { class: "eyebrow" }, "Collections"),
    shown.map((c) => h("a", { href: `#/collection/${c.key}`, ...(current.colId === c.key ? { "aria-current": "page" } : {}) },
      collIcon(c.name), h("span", { class: "name" }, c.name), h("span", { class: "c" }, c.count))),
    rest.length ? h("button", { type: "button", class: "more-cols", "aria-expanded": String(sideExpanded),
      onclick: () => { sideExpanded = !sideExpanded; renderSide(); } },
      sideExpanded ? "Show fewer" : `See ${rest.length} more ${rest.length === 1 ? "collection" : "collections"}`) : null);
}

function renderSide() {
  const home = state.home, side = $("#side");
  put(side,
    brandLogo(),
    h("div", { class: "nav" },
      h("a", { href: "#/", ...(current.name === "library" && current.colId === null ? { "aria-current": "page" } : {}) }, h("span", { class: "ico" }, icons.grid(18)), "Library"),
      h("a", { href: "#/all", ...(current.name === "all" ? { "aria-current": "page" } : {}) }, h("span", { class: "ico" }, icons.rows(18)), "All recordings"),
      h("a", { href: "#/search", ...(current.name === "search" ? { "aria-current": "page" } : {}) }, h("span", { class: "ico" }, icons.search(18)), "Search"),
      h("a", { href: "#/import", ...(current.name === "import" ? { "aria-current": "page" } : {}) }, h("span", { class: "ico" }, icons.upload(18)), "Import")),
    collectionsNav(home),
    h("div", { class: "grow" }),
    h("div", { class: "side-foot" },
      h("a", { href: "#/attention", class: `attn${home && home.attention_count ? "" : " none"}` }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", {}, "Needs attention"),
        home && home.attention_count ? h("span", { class: "n" }, home.attention_count) : null),
      syncLine(),
      h("a", { class: "manual-link", href: "/manual", target: "_blank", rel: "noopener" }, "Manual: start, stop, settings ↗"),
      h("p", { class: "privacy" }, h("span", { class: "ico" }, icons.lock(16)), h("span", {}, "Audio stays on this computer. Transcript text is sent to Claude to write titles and answer questions."))));
}

async function route() {
  shared.stop();
  if (current.cleanup) { try { current.cleanup(); } catch (_) { /* ignore */ } current.cleanup = null; }
  const hash = location.hash || "#/";
  const [path, qs] = hash.split("?");
  const main = $("#main");
  main.replaceChildren();
  main.className = "main";
  if (state.settings && !state.settings.claude) {
    main.append(h("div", { class: "notice" }, `${state.settings.reason}. Titles, summaries and full questions need it, so for now searches are basic.`));
  }
  for (const [rx, name, view] of routes) {
    const m = rx.exec(path);
    if (!m) continue;
    current = { name, cleanup: null, colId: view === collection ? m[1] : null };
    renderSide();
    window.scrollTo(0, 0);
    try { current.cleanup = (await view({ main, params: m.slice(1), query: new URLSearchParams(qs || "") })) || null; }
    catch (err) { main.append(h("div", { class: "col" }, h("div", { class: "empty" }, `Something went wrong: ${err.message}`))); }
    return;
  }
  main.append(h("div", { class: "col" }, h("div", { class: "empty" }, "That page doesn't exist. ", h("a", { class: "link", href: "#/" }, "Back to the library"))));
}

bus.addEventListener("refresh", renderSide);
window.addEventListener("hashchange", route);
(async () => {
  try { state.settings = await api("/api/settings"); } catch (_) { /* the notice just won't show */ }
  try { await refreshHome(); } catch (_) { /* sidebar renders without counts */ }
  await refreshSync();
  setInterval(refreshSync, 15000);   // keeps "Synced 3 min ago" honest while the page is open
  route();
})();
