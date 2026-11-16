// Small helpers shared by every screen. No framework: plain DOM.
export const $ = (sel, root = document) => root.querySelector(sel);

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}

// replaceChildren that ignores null/undefined/false and flattens arrays (the raw DOM call would print "null").
export function put(el, ...kids) {
  el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false));
  return el;
}

export async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
  if (opts.body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.body); }
  const r = await fetch(path, init);
  let data = null;
  try { data = await r.json(); } catch (_) { /* not JSON */ }
  if (!r.ok) throw new Error((data && (data.detail || data.message)) || `Something went wrong (${r.status})`);
  return data;
}

const SVG = "http://www.w3.org/2000/svg";
export function svg(paths, { size = 16, fill = false, stroke = 2 } = {}) {
  const s = document.createElementNS(SVG, "svg");
  s.setAttribute("width", size); s.setAttribute("height", size); s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.setAttribute("fill", fill ? "currentColor" : "none");
  if (!fill) { s.setAttribute("stroke", "currentColor"); s.setAttribute("stroke-width", stroke); s.setAttribute("stroke-linecap", "round"); s.setAttribute("stroke-linejoin", "round"); }
  for (const d of [].concat(paths)) { const p = document.createElementNS(SVG, "path"); p.setAttribute("d", d); s.append(p); }
  return s;
}
export const icons = {
  play: (n = 12) => svg("M6 3.5v17l14-8.5z", { size: n, fill: true }),
  pause: (n = 14) => svg(["M7 4h3.5v16H7z", "M13.5 4H17v16h-3.5z"], { size: n, fill: true }),
  search: (n = 24) => svg(["M11 18a7 7 0 100-14 7 7 0 000 14z", "M20 20l-3.5-3.5"], { size: n }),
  back: (n = 14) => svg("M15 5l-7 7 7 7", { size: n }),
  check: (n = 16) => svg("M5 12.5l4.5 4.5L19 7.5", { size: n, stroke: 2.2 }),
  upload: (n = 26) => svg(["M12 16V4M7 9l5-5 5 5", "M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"], { size: n, stroke: 1.8 }),
};

export function fmtDur(s) {
  if (s === null || s === undefined || isNaN(s)) return "";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}
export function fmtDate(iso, { year = null, time = false } = {}) {
  if (!iso) return "date unknown";
  const d = new Date(iso);
  const showYear = year === null ? d.getFullYear() !== new Date().getFullYear() : year;
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(showYear ? { year: "numeric" } : {}) });
  return time ? `${day}, ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : day;
}
export const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;

const SOUND_WORDS = { baby_babble: "baby babbling", baby_laugh: "baby laughing", baby_cry: "baby crying", crying: "crying",
  whimper: "whimpering", giggle: "giggling", laughter: "laughter", child_speech: "a child speaking" };
export const soundWord = (label) => SOUND_WORDS[label] || String(label).replace(/_/g, " ");

let toastTimer = null;
export function toast(msg) {
  document.querySelector(".toast")?.remove();
  const t = h("div", { class: "toast", role: "status" }, msg);
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), 3500);
}

export const bus = new EventTarget();           // "refresh" = counts changed; "audio" = something started playing
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));

// One shared audio element for the play buttons in lists. Only one thing plays at a time.
class Shared {
  constructor() { this.el = new Audio(); this.el.preload = "none"; this.id = null;
    this.el.addEventListener("ended", () => this.change()); this.el.addEventListener("pause", () => this.change());
    this.el.addEventListener("play", () => this.change());
    bus.addEventListener("audio", (e) => { if (e.detail !== "list") this.el.pause(); }); }
  change() { emit("listaudio", { id: this.id, playing: !this.el.paused }); }
  toggle(id, at = 0) {
    if (this.id === id && !this.el.paused) { this.el.pause(); return; }
    if (this.id !== id) { this.id = id; this.el.src = `/api/notes/${id}/audio`; }
    emit("audio", "list");
    const go = () => { if (at) this.el.currentTime = at; this.el.play().catch(() => {}); };
    if (this.el.readyState >= 1) go(); else this.el.addEventListener("loadedmetadata", go, { once: true });
    this.change();
  }
  stop() { this.el.pause(); }
}
export const shared = new Shared();
