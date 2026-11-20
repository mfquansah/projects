// Search results. Typing shows instant local results; Enter (or arriving with ?q=) asks the full question.
import { h, api, fmtDate, put } from "../util.js";
import { state, go } from "../core.js";
import { searchBox, resultCards } from "./common.js";

const WINDOWS = { any: null, week: 7, month: 31, year: 366 };

function understood(u) {
  const bits = [];
  if (u.topic) bits.push(`about ${u.topic}`);
  if (u.category) bits.push(`in ${u.category}`);
  if (u.since || u.until) bits.push(`${u.since ? fmtDate(u.since, { year: true }) : "…"} to ${u.until ? fmtDate(u.until, { year: true }) : "…"}`);
  if (u.sort) bits.push(`${u.sort}${u.count ? ` (top ${u.count})` : ""}`);
  if (u.sound) bits.push(`sound: ${u.sound.replace(/_/g, " ")}`);
  return bits.length ? `Understood as: ${bits.join(" · ")}` : "";
}

export async function search({ main, query }) {
  const startQ = query.get("q") || "";
  let hits = [], seq = 0, timer = null, mode = "idle", verdict = null, notes = [], und = "";
  const f = { cat: "", when: "any", tag: "" };

  const out = h("div", {});
  const status = h("div", { class: "status", role: "status", "aria-live": "polite" });
  const filterRow = h("div", { class: "filters" });
  const box = searchBox({
    value: startQ,
    onInput: (v) => { clearTimeout(timer); const q = v.trim(); if (!q) { ++seq; hits = []; mode = "idle"; paint(); return; } timer = setTimeout(() => instant(q), 250); },
    onSubmit: (q) => { if (!q) return; if (q === (new URLSearchParams((location.hash.split("?")[1]) || "").get("q"))) ask(q); else go(`#/search?q=${encodeURIComponent(q)}`); },
  });

  main.append(h("div", { class: "col" }, box.el, filterRow, status, out));

  function filtered() {
    return hits.filter((x) => {
      if (f.cat && x.category !== f.cat) return false;
      if (f.tag && !(x.tags || []).includes(f.tag)) return false;
      const days = WINDOWS[f.when];
      if (days && (!x.recorded_at || Date.now() - new Date(x.recorded_at).getTime() > days * 864e5)) return false;
      return true;
    });
  }
  function select(label, key, options) {
    const s = h("select", { "aria-label": label, onchange: (e) => { f[key] = e.target.value; paint(); } },
      options.map(([v, t]) => h("option", { value: v, selected: f[key] === v }, t)));
    return s;
  }
  function paint() {
    const cats = (state.home?.categories || []).filter((c) => c.id !== null);
    const tags = [...new Set(hits.flatMap((x) => x.tags || []))].sort();
    put(filterRow, 
      select("Collection", "cat", [["", "All collections"], ...cats.map((c) => [c.name, c.name])]),
      select("Date recorded", "when", [["any", "Any time"], ["week", "Past week"], ["month", "Past month"], ["year", "Past year"]]),
      select("Tag", "tag", [["", "All tags"], ...tags.map((t) => [t, t])]));
    filterRow.style.display = hits.length ? "" : "none";
    const shown = filtered();
    out.replaceChildren();
    if (mode === "ask") {
      out.append(h("div", { class: "verdict" },
        h("h1", {}, verdict || (hits.length ? `${hits.length} result${hits.length === 1 ? "" : "s"}` : "No matches")),
        verdict && hits.length > 1 ? h("span", { class: "muted", style: "font-size:14px" }, `${hits.length} results`) : null));
      if (und) out.append(h("div", { class: "muted", style: "font-size:14px;margin:6px 4px 0" }, und));
      for (const n of notes) out.append(h("div", { class: "sysnote" }, n));
      out.append(resultCards(shown, hits.length ? "Nothing left after those filters." : "No matches. Try different words, or ask about a sound or a date."));
    } else if (mode === "instant") {
      out.append(h("div", { class: "muted", style: "margin:24px 4px 0;font-size:14px" }, "Instant results from this computer. Press Enter for a full answer."));
      out.append(resultCards(shown, "No instant matches. Press Enter to ask the full question."));
    } else {
      out.append(h("div", { class: "empty" }, "Type to search, or press Enter to ask a full question."));
    }
  }
  async function instant(q) {
    const my = ++seq;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}&limit=12`);
      if (my !== seq) return;
      hits = r.hits; mode = "instant"; status.textContent = ""; paint();
    } catch (err) { status.textContent = err.message; }
  }
  async function ask(q) {
    const my = ++seq;
    box.busy(true);
    status.textContent = state.settings?.claude ? "Asking Claude to understand your question…" : "Searching…";
    try {
      const r = await api("/api/ask", { body: { q, limit: 12 } });
      if (my !== seq) return;
      hits = r.hits; verdict = r.verdict; notes = r.notes; und = understood(r.understood); mode = "ask"; status.textContent = ""; paint();
    } catch (err) { if (my === seq) status.textContent = err.message; }
    finally { box.busy(false); }
  }

  paint();
  if (startQ) await ask(startQ);
  return () => { clearTimeout(timer); ++seq; };
}
