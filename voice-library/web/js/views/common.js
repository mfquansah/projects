// Pieces used by more than one screen.
import { h, icons, bus, shared, fmtDate, fmtDur, soundWord } from "../util.js";

export function searchBox({ value = "", onInput, onSubmit, autofocus = true } = {}) {
  const input = h("input", { id: "q", type: "search", placeholder: "Find a thought, recording or memory…", autocomplete: "off",
    "aria-label": "Search your recordings", value });
  const form = h("form", { class: "searchbox", role: "search", onsubmit: (e) => { e.preventDefault(); onSubmit && onSubmit(input.value.trim()); } },
    icons.search(24), input, h("div", { class: "pulse", "aria-hidden": "true" }, h("i"), h("i"), h("i"), h("i")));
  input.addEventListener("input", () => onInput && onInput(input.value));
  if (autofocus) queueMicrotask(() => { input.focus(); input.setSelectionRange(input.value.length, input.value.length); });
  return { el: form, input, busy: (b) => form.classList.toggle("busy", !!b) };
}

// Play buttons in lists all reflect the one shared audio element.
export function playButton(id) {
  const b = h("button", { type: "button", class: "playbtn", "data-id": id, "aria-label": "Play", onclick: (e) => { e.preventDefault(); shared.toggle(id); } }, icons.play(12));
  return b;
}
bus.addEventListener("listaudio", (e) => {
  for (const b of document.querySelectorAll(".playbtn")) {
    const on = e.detail.playing && String(e.detail.id) === b.dataset.id;
    b.classList.toggle("on", on);
    b.setAttribute("aria-label", on ? "Pause" : "Play");
    b.replaceChildren(on ? icons.pause(12) : icons.play(12));
  }
});

export const lengthText = (hit) => (hit.duration_s ? fmtDur(hit.duration_s) : "");

// Quiet rows (Library, a collection, instant results).
export function noteRows(hits, emptyText) {
  if (!hits.length) return h("div", { class: "empty" }, emptyText);
  return h("div", {}, hits.map((x, i) => h("div", { class: "row" },
    h("span", { class: "num" }, String(i + 1).padStart(2, "0")),
    playButton(x.id),
    h("a", { class: "rowbody", href: `#/note/${x.id}` }, h("span", { class: "t" }, x.title), h("span", { class: "s" }, x.summary)),
    h("div", { class: "rowmeta" }, h("span", { class: "cat" }, x.category || "Uncategorized"),
      h("span", {}, [fmtDate(x.recorded_at), lengthText(x)].filter(Boolean).join(" · "))))));
}

const LABELS = { match: "Match", partial: "Partly", related: "Related" };

// Search results: label, serif title, the matching moment with a timestamp, and (for the top one) Claude's reason.
export function resultCards(hits, emptyText) {
  if (!hits.length) return h("div", { class: "empty" }, emptyText);
  return h("div", {}, hits.map((x) => {
    const sn = x.snippet;
    const meta = [x.category || "Uncategorized", fmtDate(x.recorded_at, { year: true }), lengthText(x)].filter(Boolean).join(" · ");
    return h("article", { class: "result" },
      x.strength ? h("div", { class: `label ${x.strength}` }, h("span", { class: "d" }), LABELS[x.strength]) : null,
      h("a", { class: "rtitle", href: `#/note/${x.id}` }, x.title),
      h("div", { class: "rmeta" }, meta),
      sn ? h("div", { class: "snip" },
        sn.t !== null && sn.t !== undefined ? h("a", { class: "chip", href: `#/note/${x.id}?t=${Math.floor(sn.t)}`, "aria-label": `Play from ${fmtDur(sn.t)}` }, icons.play(9), fmtDur(sn.t)) : null,
        h("p", {}, sn.parts.map((p) => (p.m ? h("mark", {}, p.t) : p.t))))
        : (x.summary ? h("p", { class: "snip", style: "margin:4px 0 0" }, x.summary) : null),
      soundChip(x),
      x.why ? h("p", { class: "why" }, x.why) : null);
  }));
}

function soundChip(x) {
  if (!x.sound_info) return null;
  const m = /^(\S+) [\d.]+ at (\d+):(\d+)/.exec(x.sound_info);
  if (!m) return null;
  const t = Math.max(0, Math.floor(x.sound_start_s ?? (+m[2] * 60 + +m[3])));
  return h("div", { class: "snip" }, h("a", { class: "chip sound", href: `#/note/${x.id}?t=${Math.max(0, t - 1)}` }, icons.play(9), `${x.sound_conf !== null && x.sound_conf !== undefined && x.sound_conf < 0.3 ? "possibly " : ""}${soundWord(m[1])} at ${fmtDur(t)}`));
}

export function emptyLibrary() {
  return h("div", { class: "empty" }, "Nothing here yet. ", h("a", { class: "link", href: "#/import" }, "Import some voice notes"), " to get started.");
}
