// Starts the app: sidebar, routing between screens, and the "Claude isn't connected" notice.
import { $, h, api, bus, shared, put } from "./util.js";
import { state, refreshHome, refreshSync, ago } from "./core.js";
import { library, collection } from "./views/library.js";
import { search } from "./views/search.js";
import { note } from "./views/note.js";
import { importView } from "./views/import.js";
import { attention } from "./views/attention.js";

const routes = [
  [/^#\/?$/, "library", library],
  [/^#\/collection\/(\w+)$/, "library", collection],
  [/^#\/search$/, "search", search],
  [/^#\/note\/(\d+)$/, "library", note],
  [/^#\/import$/, "import", importView],
  [/^#\/attention$/, "attention", attention],
];
let current = { name: "library", cleanup: null, colId: null };

function syncLine() {
  const sy = state.sync;
  if (!sy || !sy.available) return null;
  if (!sy.enabled) return null;   // the switch is shelved; nothing to point at while sync is off
  if (sy.problem) return h("a", { href: "#/import", class: "sync warn" }, "Sync paused. Tap for help.");
  const text = sy.pending > 0 ? `Syncing · ${sy.pending} importing` : (sy.last ? `Synced ${ago(sy.last.at)}${sy.last.new ? ` · ${sy.last.new} new` : ""}` : "Sync starting…");
  return h("div", { class: "sync" }, h("span", {}, text), " ",
    h("button", { type: "button", class: "link", onclick: async () => { try { await api("/api/sync/run", { method: "POST", body: {} }); } catch (_) { /* shown on refresh */ } refreshSync(); } }, "Sync now"));
}

function renderSide() {
  const home = state.home, side = $("#side");
  put(side,
    h("div", { class: "brand" }, h("div", { class: "mark", "aria-hidden": "true" }, [["#0E6B47", 14], ["#E9A912", 25], ["#C8402A", 18], ["#E9A912", 9]].map(([c, ht]) => h("i", { style: `height:${ht}px;background:${c}` }))),
      h("div", { class: "word" }, h("b", {}, "kasa"), h("span", {}, "adaka"))),
    h("div", { class: "nav" },
      h("a", { href: "#/", ...(current.name === "library" && current.colId === null ? { "aria-current": "page" } : {}) }, "Library"),
      h("a", { href: "#/search", ...(current.name === "search" ? { "aria-current": "page" } : {}) }, "Search"),
      h("a", { href: "#/import", ...(current.name === "import" ? { "aria-current": "page" } : {}) }, "Import")),
    h("div", { class: "cols" }, h("p", { class: "eyebrow" }, "Collections"),
      (home?.categories || []).filter((c) => c.count > 0 || c.id !== null).map((c, i) => {
        const id = c.id === null ? "none" : String(c.id);
        return h("a", { href: `#/collection/${id}`, ...(current.colId === id ? { "aria-current": "page" } : {}) },
          h("span", { class: "n" }, String(i + 1).padStart(2, "0")), h("span", { class: "name" }, c.name), h("span", { class: "c" }, c.count));
      })),
    h("div", { class: "grow" }),
    h("div", { class: "side-foot" },
      h("a", { href: "#/attention", class: `attn${home && home.attention_count ? "" : " none"}` }, h("span", { class: "dot", "aria-hidden": "true" }), h("span", {}, "Needs attention"),
        home && home.attention_count ? h("span", { class: "n" }, home.attention_count) : null),
      syncLine(),
      h("p", { class: "privacy" }, "Audio stays on this computer. Transcript text is sent to Claude to write titles and answer questions.")));
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
