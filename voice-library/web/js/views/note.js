// One recording: player with waveform and sound markers, summary, tags, timestamped transcript, details, related.
import { h, api, bus, emit, icons, fmtDur, fmtDate, soundWord, toast, put } from "../util.js";
import { state, go, refreshHome } from "../core.js";

const N = 96;                                   // bars in the waveform
const SPEEDS = [1, 1.25, 1.5, 2, 0.75];
const DATE_FROM = { metadata: "the audio file", filename: "the file name", "file-modified": "the file's modified time",
  birthtime: "file time (may be the import time)", mtime: "file time (may be the import time)", unknown: "unknown" };

export async function note({ main, params, query }) {
  const id = Number(params[0]);
  let d;
  let confirmingDelete = false;
  let sharing = false, shareInfo = null;
  try { d = await api(`/api/notes/${id}`); }
  catch (err) { main.append(h("div", { class: "col" }, h("a", { class: "back", href: "#/" }, "← Library"), h("div", { class: "empty" }, err.message))); return; }

  const audio = new Audio();
  audio.preload = "metadata";
  audio.src = `/api/notes/${id}/audio`;
  const onOtherAudio = (e) => { if (e.detail === "list") audio.pause(); };
  bus.addEventListener("audio", onOtherAudio);

  let editing = false, speed = 0, findText = "";
  const dur = () => (isFinite(audio.duration) && audio.duration > 0 ? audio.duration : d.duration_s || 0);

  // ---------- header ----------
  const header = h("header", { style: "display:flex;flex-direction:column;gap:8px" });
  // ---------- player ----------
  const barEls = Array.from({ length: N }, () => h("i", { style: "height:22px" }));
  const bars = h("div", { class: "bars", role: "slider", tabindex: "0", "aria-label": "Playback position", "aria-valuemin": "0" }, barEls);
  const wave = h("div", { class: "wave" }, bars);
  const timeEl = h("span", { class: "time" }, `0:00 / ${fmtDur(dur())}`);
  const playBtn = h("button", { type: "button", class: "big", "aria-label": "Play", onclick: toggle }, icons.play(16));
  const speedBtn = h("button", { type: "button", class: "ghost", "aria-label": "Playback speed", style: "padding:4px 10px", onclick: () => {
    speed = (speed + 1) % SPEEDS.length; audio.playbackRate = SPEEDS[speed]; speedBtn.textContent = `${SPEEDS[speed]}×`; } }, "1×");
  const soundsLine = h("div", { class: "soundsline" });
  const player = h("section", { "aria-label": "Player", style: "display:flex;flex-direction:column;gap:14px" }, wave,
    h("div", { class: "controls" },
      h("button", { type: "button", class: "skip", "aria-label": "Back 10 seconds", onclick: () => seek(audio.currentTime - 10) }, "−10s"),
      playBtn,
      h("button", { type: "button", class: "skip", "aria-label": "Forward 10 seconds", onclick: () => seek(audio.currentTime + 10) }, "+10s"),
      timeEl, h("div", { class: "grow" }), speedBtn),
    soundsLine);

  function toggle() { if (audio.paused) { emit("audio", "note"); audio.play().catch(() => {}); } else audio.pause(); }
  function seek(t, play = false) {
    const total = dur();
    audio.currentTime = Math.max(0, total ? Math.min(total - 0.05, t) : t);
    if (play && audio.paused) { emit("audio", "note"); audio.play().catch(() => {}); }
    tick();
  }
  const frac = (e) => { const r = bars.getBoundingClientRect(); return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)); };
  bars.addEventListener("click", (e) => seek(frac(e) * dur()));
  bars.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); seek(audio.currentTime - 5); }
    else if (e.key === "ArrowRight") { e.preventDefault(); seek(audio.currentTime + 5); }
    else if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); }
  });
  audio.addEventListener("play", () => { playBtn.replaceChildren(icons.pause(16)); playBtn.setAttribute("aria-label", "Pause"); });
  audio.addEventListener("pause", () => { playBtn.replaceChildren(icons.play(16)); playBtn.setAttribute("aria-label", "Play"); });
  audio.addEventListener("timeupdate", tick);
  audio.addEventListener("loadedmetadata", () => { tick(); drawMarkers(); });

  let activeIdx = -1;
  function tick() {
    const total = dur(), t = audio.currentTime || 0, f = total ? t / total : 0;
    const upto = Math.floor(f * N);
    barEls.forEach((b, i) => b.classList.toggle("on", i < upto));
    timeEl.textContent = `${fmtDur(t)} / ${fmtDur(total)}`;
    bars.setAttribute("aria-valuenow", String(Math.round(t))); bars.setAttribute("aria-valuemax", String(Math.round(total)));
    bars.setAttribute("aria-valuetext", `${fmtDur(t)} of ${fmtDur(total)}`);
    let idx = -1;
    d.segments.forEach((s, i) => { if (s.start <= t + 0.05) idx = i; });
    if (idx !== activeIdx) { activeIdx = idx; segEls.forEach((el, i) => el.classList.toggle("active", i === idx)); }
  }

  // waveform shape from the server (a flat row until it arrives, or if the audio can't be read)
  api(`/api/notes/${id}/peaks?n=${N}`).then((r) => r.peaks.forEach((p, i) => { barEls[i].style.height = `${Math.round(10 + p * 54)}px`; })).catch(() => {
    barEls.forEach((b) => { b.style.height = "26px"; });
  });

  // sounds heard: dots on the waveform + a line of links
  const sounds = d.sounds.filter((e) => e.confidence >= 0.3 && ["baby_babble", "baby_laugh", "baby_cry", "crying", "whimper", "giggle", "laughter"].includes(e.label));
  function drawMarkers() {
    wave.querySelectorAll(".mark-dot").forEach((m) => m.remove());
    const total = dur();
    if (!total) return;
    for (const e of sounds) wave.append(h("button", { type: "button", class: "mark-dot", style: `left:${(e.start_s / total) * 100}%`,
      title: `${soundWord(e.label)} at ${fmtDur(e.start_s)}`, "aria-label": `${soundWord(e.label)} at ${fmtDur(e.start_s)}`, onclick: () => seek(Math.max(0, e.start_s - 1), true) }));
  }
  if (sounds.length) {
    const seen = new Map();
    for (const e of sounds) if (!seen.has(e.label) || e.confidence > seen.get(e.label).confidence) seen.set(e.label, e);
    put(soundsLine, h("span", {}, "Heard in this recording"),
      [...seen.values()].map((e) => h("button", { type: "button", onclick: () => seek(Math.max(0, e.start_s - 1), true) }, `${soundWord(e.label)} at ${fmtDur(e.start_s)}`)));
  }
  drawMarkers();

  // ---------- summary + tags ----------
  const summaryBox = h("section", { style: "display:flex;flex-direction:column;gap:12px" });
  // ---------- transcript ----------
  let segEls = [];
  const transBox = h("section", { style: "display:flex;flex-direction:column;gap:8px" });
  function drawTranscript() {
    const q = findText.trim().toLowerCase();
    const find = h("input", { type: "search", placeholder: "Find in transcript", "aria-label": "Find in transcript", value: findText,
      oninput: (e) => { findText = e.target.value; drawTranscript(); find2.focus(); } });
    const find2 = find;
    put(transBox, h("div", { class: "transhead" }, h("h2", { class: "eyebrow ul" }, "Transcript"), find));
    segEls = [];
    if (!d.segments.length) {
      transBox.append(h("p", { class: "summary", style: "font-size:15px" }, d.transcript || "(no speech was transcribed)"));
      return;
    }
    let shown = 0;
    d.segments.forEach((s, i) => {
      if (q && !s.text.toLowerCase().includes(q)) { segEls.push(h("div")); return; }
      const parts = [];
      if (q) { let rest = s.text, low = rest.toLowerCase(), at; while ((at = low.indexOf(q)) >= 0) { parts.push(rest.slice(0, at), h("mark", {}, rest.slice(at, at + q.length))); rest = rest.slice(at + q.length); low = rest.toLowerCase(); } parts.push(rest); }
      const el = h("div", { class: `seg${i === activeIdx ? " active" : ""}` },
        h("button", { type: "button", class: "t", "aria-label": `Play from ${fmtDur(s.start)}`, onclick: () => seek(s.start, true) }, fmtDur(s.start)),
        h("span", {}, q ? parts : s.text));
      segEls.push(el); transBox.append(el); shown++;
    });
    if (q && !shown) transBox.append(h("div", { class: "empty" }, "Nothing in this transcript matches."));
  }

  // ---------- side rail ----------
  const side = h("aside", { class: "noteSide" });
  function drawSide() {
    const rows = [["Recorded", fmtDate(d.recorded_at, { year: true, time: true })], ["Length", fmtDur(d.duration_s)], ["Collection", d.category || "Uncategorized"],
      ["Imported", d.imported_at ? fmtDate(d.imported_at, { year: true }) : "—"], ["Date from", DATE_FROM[d.date_source] || d.date_source], ["File", d.file]];
    put(side,
      h("section", { style: "display:flex;flex-direction:column;gap:10px" }, h("h2", { class: "eyebrow ul" }, "Details"),
        h("dl", { class: "det" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))),
      d.related && d.related.length ? h("section", { class: "related" }, h("h2", { class: "eyebrow ul", style: "margin-bottom:6px" }, "Related"),
        d.related.map((r) => h("a", { href: `#/note/${r.id}` }, h("b", {}, r.title), h("span", {}, [r.category, fmtDate(r.recorded_at, { year: true })].filter(Boolean).join(" · "))))) : null,
      sharing ? sharePanel() : null,
      confirmingDelete ? deleteConfirm() : h("div", { style: "display:flex;flex-direction:column;gap:8px" },
        sharing ? null : h("button", { type: "button", class: "ghost", onclick: openShare }, "Share by email…"),
        h("a", { class: "ghost", href: `/api/notes/${id}/download`, download: "" }, "Download audio"),
        h("button", { type: "button", class: "ghost", onclick: async () => {
          try { await api(`/api/notes/${id}/flag`, { body: { flag: "archived" } }); await refreshHome(); toast("Archived. You can restore it from Needs attention."); go("#/"); }
          catch (err) { toast(err.message); } } }, "Archive this recording"),
        h("button", { type: "button", class: "ghost danger", onclick: () => { confirmingDelete = true; drawSide(); } }, "Delete permanently…")));
  }

  async function openShare() {
    sharing = true;
    shareInfo = null;
    drawSide();
    try { shareInfo = await api(`/api/notes/${id}/share`); } catch (err) { toast(err.message); sharing = false; }
    drawSide();
  }

  function sharePanel() {
    const info = shareInfo;
    const to = h("input", { id: "share-to", type: "email", placeholder: "name@example.com", autocomplete: "off" });
    const msg = h("textarea", { id: "share-msg", rows: "3", placeholder: "Write a note to go with the recording" });
    const sum = h("input", { type: "checkbox" }), tr = h("input", { type: "checkbox" });
    const status = h("p", { class: "muted", style: "margin:0;font-size:14px", role: "status" });
    const mailBtn = h("button", { type: "button", class: "ghost solid-ink", disabled: info && !info.mail_available ? "true" : null, onclick: async () => {
      mailBtn.disabled = true; status.textContent = "Opening Mail…";
      try {
        await api(`/api/notes/${id}/share/mail`, { body: { to: to.value, message: msg.value, include_summary: sum.checked, include_transcript: tr.checked } });
        status.textContent = "The draft is open in Mail. Check it there and press Send.";
      } catch (err) { status.textContent = err.message; }
      mailBtn.disabled = false; } }, "Open in Mail");
    return h("div", { class: "share-panel", role: "group", "aria-label": "Share this recording" },
      h("div", { style: "display:flex;align-items:flex-start;justify-content:space-between;gap:8px;margin-bottom:8px" },
        h("strong", {}, "Share by email"),
        h("button", { type: "button", class: "x-close", "aria-label": "Close", title: "Close", onclick: () => { sharing = false; drawSide(); } }, "×")),
      !info ? h("p", { class: "muted", style: "margin:0" }, "Loading…") : [
        h("p", { class: "muted", style: "margin:0 0 10px;font-size:14px" }, `Attached as "${info.filename}" (${info.size_mb} MB).`),
        info.too_big ? h("p", { class: "sysnote", style: "margin:0 0 10px" }, `This is over ${info.limit_mb} MB, which many email services won't accept. Share a shorter recording, or use Download and send it another way.`) : null,
        h("div", { style: "display:flex;flex-direction:column;gap:10px" },
          h("div", { class: "field" }, h("label", { for: "share-to" }, "Email address"), to),
          h("div", { class: "field" }, h("label", { for: "share-msg" }, "Message ", h("span", { class: "muted" }, "(optional)")), msg),
          h("label", { class: "check" }, sum, " Include the summary"),
          h("label", { class: "check" }, tr, " Include the transcript")),
        h("p", { class: "muted", style: "margin:12px 0 0;font-size:13px" },
          info.mail_available ? "This opens a draft in the Mail app with the recording attached. You review it there and press Send; nothing is sent from here."
                              : "Mail drafts need a Mac with the Mail app, so this can't open one here."),
        h("div", { style: "margin-top:10px" }, mailBtn),
        h("div", { style: "margin-top:8px" }, status)]);
  }

  function deleteConfirm() {
    return h("div", { class: "confirm-delete", role: "alertdialog", "aria-label": "Delete this recording?" },
      h("p", { style: "margin:0 0 6px" }, h("strong", {}, "Delete this recording for good?")),
      h("p", { class: "muted", style: "margin:0 0 10px;font-size:14px" },
        "This removes its transcript, title, summary and this app's copy of the audio. Your original in Voice Memos is not touched, and this recording will not be imported again. It can't be undone."),
      h("div", { style: "display:flex;gap:8px;flex-wrap:wrap" },
        h("button", { type: "button", class: "ghost danger solid", onclick: async () => {
          try { await api(`/api/notes/${id}`, { method: "DELETE" }); await refreshHome(); toast("Deleted."); go("#/"); }
          catch (err) { confirmingDelete = false; drawSide(); toast(err.message); } } }, "Yes, delete it"),
        h("button", { type: "button", class: "ghost", onclick: () => { confirmingDelete = false; drawSide(); } }, "Cancel")));
  }

  async function save(body) {
    try { d = { ...d, ...(await api(`/api/notes/${id}`, { method: "PATCH", body })) }; await refreshHome(); return true; }
    catch (err) { toast(err.message); return false; }
  }

  function drawTop() {
    const cats = (state.home?.categories || []).filter((c) => c.id !== null);
    const sel = h("select", { "aria-label": "Collection", onchange: async (e) => {
        try { await api(`/api/notes/${id}/category`, { body: { category_id: e.target.value === "" ? null : Number(e.target.value) } });
          d = { ...d, ...(await api(`/api/notes/${id}`)) }; await refreshHome(); toast("Moved."); render(); }
        catch (err) { toast(err.message); } } },
      h("option", { value: "" }, "Uncategorized"), cats.map((c) => h("option", { value: c.id, selected: c.id === d.category_id }, c.name)));
    const editedNote = d.edited.length ? `You've edited this recording's ${d.edited.join(", ")}.` : "Title and collection were suggested automatically.";
    if (editing) {
      const title = h("input", { class: "edit title", value: d.title, "aria-label": "Title", maxlength: "200" });
      const summary = h("textarea", { class: "edit", "aria-label": "Summary", maxlength: "2000" }, d.summary);
      put(header, title, h("div", { class: "metaline" }, sel), h("div", { class: "actions" },
        h("button", { type: "button", class: "primary", onclick: async () => { if (await save({ title: title.value, summary: summary.value })) { editing = false; render(); toast("Saved."); } } }, "Save"),
        h("button", { type: "button", class: "ghost", onclick: () => { editing = false; render(); } }, "Cancel")));
      drawSummary(summary);
      queueMicrotask(() => title.focus());
    } else {
      put(header,
        h("div", { class: "titlerow" }, h("h1", { class: "ntitle" }, d.title), h("button", { type: "button", class: "ghost", style: "margin-top:8px", onclick: () => { editing = true; render(); } }, "Edit")),
        h("div", { class: "metaline" }, sel, h("span", {}, "·"), h("span", {}, fmtDate(d.recorded_at, { year: true })), d.duration_s ? [h("span", {}, "·"), h("span", {}, fmtDur(d.duration_s))] : null),
        h("div", { class: "small" }, editedNote));
      drawSummary(null);
    }
  }
  function drawSummary(editor) {
    const tags = h("div", { class: "tags" }, d.tags.map((t) => h("span", { class: "tag" }, t,
      editing ? h("button", { type: "button", "aria-label": `Remove ${t}`, onclick: async () => { if (await save({ tags: d.tags.filter((x) => x !== t) })) render(); } }, "×") : null)));
    const add = h("button", { type: "button", class: "tagadd", onclick: () => {
      const input = h("input", { class: "tagin", "aria-label": "New tag", maxlength: "40", placeholder: "tag" });
      const commit = async () => { const v = input.value.trim(); if (v && await save({ tags: [...d.tags, v] })) render(); else add.replaceChildren(); render(); };
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } if (e.key === "Escape") render(); });
      input.addEventListener("blur", () => { if (!input.value.trim()) render(); });
      add.replaceWith(input); input.focus(); } }, "+ Add tag");
    tags.append(add);
    put(summaryBox, h("h2", { class: "eyebrow ul" }, "Summary"), editor || h("p", { class: "summary" }, d.summary || "No summary yet."), tags);
  }
  function render() { drawTop(); drawTranscript(); drawSide(); }

  main.append(h("div", { class: "col wide" },
    h("a", { class: "back", href: "#/" }, icons.back(14), "Library"),
    h("div", { class: "noteGrid" }, h("div", { class: "noteMain" }, header, player, summaryBox, transBox), side)));
  render();
  tick();

  // arriving from a search result: jump to the moment
  const t0 = Number(query.get("t"));
  if (query.get("t") !== null && !isNaN(t0)) {
    const go0 = () => seek(t0, true);
    if (audio.readyState >= 1) go0(); else audio.addEventListener("loadedmetadata", go0, { once: true });
  }
  return () => { audio.pause(); audio.removeAttribute("src"); audio.load(); bus.removeEventListener("audio", onOtherAudio); };
}
