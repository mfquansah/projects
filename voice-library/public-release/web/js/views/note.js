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
  let shareModal = null;   // the open "Share by email" card, if any
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
  const speedBtn = h("button", { type: "button", class: "ghost speedbtn", "aria-label": "Playback speed", onclick: () => {
    speed = (speed + 1) % SPEEDS.length; audio.playbackRate = SPEEDS[speed]; speedBtn.textContent = `${SPEEDS[speed]}× speed`; } }, "1× speed");
  const soundsLine = h("div", { class: "soundsline" });
  const player = h("section", { "aria-label": "Player", class: "pcard player" }, wave,
    h("div", { class: "controls" },
      h("button", { type: "button", class: "skip", "aria-label": "Back 10 seconds", onclick: () => seek(audio.currentTime - 10) }, icons.back10(22), h("b", {}, "10")),
      playBtn,
      h("button", { type: "button", class: "skip", "aria-label": "Forward 10 seconds", onclick: () => seek(audio.currentTime + 10) }, icons.fwd10(22), h("b", {}, "10")),
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
    if (idx !== activeIdx) {
      activeIdx = idx; segEls.forEach((el, i) => el.classList.toggle("active", i === idx));
      const el = segEls[idx];
      if (el && el.isConnected && !audio.paused && segsBox.scrollHeight > segsBox.clientHeight) {   // keep the spoken line in view, without moving the page
        const top = el.offsetTop - segsBox.offsetTop;
        if (top < segsBox.scrollTop || top + el.offsetHeight > segsBox.scrollTop + segsBox.clientHeight) segsBox.scrollTo({ top: Math.max(0, top - 40), behavior: "smooth" });
      }
    }
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
  const summaryBox = h("section", { class: "pcard", style: "display:flex;flex-direction:column;gap:12px" });
  // ---------- transcript ----------
  let segEls = [];
  const transBox = h("section", { class: "pcard transcard", "aria-label": "Transcript" });
  const segsBox = h("div", { class: "segs" });
  function drawTranscript() {
    const q = findText.trim().toLowerCase();
    const find = h("input", { type: "search", placeholder: "Find in transcript", "aria-label": "Find in transcript", value: findText,
      oninput: (e) => { findText = e.target.value; drawTranscript(); find2.focus(); } });
    const find2 = find;
    put(transBox, h("div", { class: "transhead" }, h("h2", { class: "eyebrow ul" }, "Transcript"), find), segsBox);
    segsBox.replaceChildren();
    segEls = [];
    if (!d.segments.length) {
      segsBox.append(h("p", { class: "summary", style: "font-size:15px" }, d.transcript || "(no speech was transcribed)"));
      return;
    }
    // Flowing text, not one row per line: segments run together in paragraphs, each with a time you can click.
    // The segment being spoken is highlighted in place, and every segment is clickable to jump there.
    const paras = [];
    d.segments.forEach((s, i) => {
      const last = paras[paras.length - 1];
      if (!last || last.n >= 4 || last.chars > 280) paras.push({ start: s.start, items: [], n: 0, chars: 0 });
      const para = paras[paras.length - 1];
      para.items.push(i); para.n++; para.chars += s.text.length;
    });
    let shown = 0;
    segEls = new Array(d.segments.length);
    for (const para of paras) {
      const p = h("p", {});
      for (const i of para.items) {
        const sg = d.segments[i];
        const parts = [];
        if (q) { let rest = sg.text, low = rest.toLowerCase(), at; while ((at = low.indexOf(q)) >= 0) { parts.push(rest.slice(0, at), h("mark", {}, rest.slice(at, at + q.length))); shown++; rest = rest.slice(at + q.length); low = rest.toLowerCase(); } parts.push(rest); }
        const el = h("span", { class: `seg${i === activeIdx ? " active" : ""}`, title: `Play from ${fmtDur(sg.start)}`, onclick: () => seek(sg.start, true) }, q ? parts : sg.text);
        segEls[i] = el; p.append(el, " ");
      }
      segsBox.append(h("div", { class: "para" },
        h("button", { type: "button", class: "t", "aria-label": `Play from ${fmtDur(para.start)}`, onclick: () => seek(para.start, true) }, fmtDur(para.start)), p));
    }
    if (q && !shown) segsBox.append(h("div", { class: "empty" }, "Nothing in this transcript matches."));
  }

  // ---------- side rail ----------
  const side = h("aside", { class: "noteSide" });
  function drawSide() {
    const rows = [["Recorded", fmtDate(d.recorded_at, { year: true, time: true })], ["Length", fmtDur(d.duration_s)], ["Collection", d.category || "Uncategorized"],
      ["Imported", d.imported_at ? fmtDate(d.imported_at, { year: true }) : "—"], ["Date from", DATE_FROM[d.date_source] || d.date_source], ["File", d.file]];
    put(side,
      h("section", { class: "pcard", style: "display:flex;flex-direction:column;gap:10px" }, h("h2", { class: "eyebrow ul" }, "Details"),
        h("dl", { class: "det" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)]))),
      d.related && d.related.length ? h("section", { class: "pcard related" }, h("h2", { class: "eyebrow ul", style: "margin-bottom:2px" }, "Related recordings"),
        d.related.map((r) => h("a", { href: `#/note/${r.id}` }, h("b", {}, r.title), h("span", {}, [r.category, fmtDate(r.recorded_at, { year: true })].filter(Boolean).join(" · "))))) : null,
      confirmingDelete ? deleteConfirm() : h("div", { style: "display:flex;flex-direction:column;gap:8px" },
        h("button", { type: "button", class: "ghost", onclick: openShare }, "Share by email…"),
        h("a", { class: "ghost", href: `/api/notes/${id}/download`, download: "" }, "Download audio"),
        h("button", { type: "button", class: "ghost", onclick: async () => {
          try { await api(`/api/notes/${id}/flag`, { body: { flag: "archived" } }); await refreshHome(); toast("Archived. You can restore it from Needs attention."); go("#/"); }
          catch (err) { toast(err.message); } } }, "Archive this recording"),
        h("button", { type: "button", class: "ghost danger", onclick: () => { confirmingDelete = true; drawSide(); } }, "Delete permanently…")));
  }

  // The share card: a centred pop-up (design from Claude Design). Static markup below; the file name and size are filled in as text.
  const MAIL_ICON = '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m4 7 8 6 8-6"/></svg>';
  const SHARE_CARD = `
    <header class="sc-head"><h2 id="sc-title">Share by email</h2>
      <button type="button" class="sc-x" aria-label="Close"><svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button></header>
    <div class="sc-file">
      <span class="sc-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28"><rect x="5" y="10" width="3" height="8" rx="1.5" fill="#1E8A5C"/><rect x="10.5" y="6" width="3" height="16" rx="1.5" fill="#EDB231"/><rect x="16" y="7" width="3" height="14" rx="1.5" fill="#D2432B"/><rect x="21.5" y="11.5" width="3" height="5" rx="1.5" fill="#EDB231"/></svg></span>
      <div class="sc-filetext"><span class="sc-name"></span><span class="sc-meta"></span></div></div>
    <p class="sysnote sc-warn" hidden></p>
    <div class="sc-field"><label for="sc-to">Send to</label><input id="sc-to" type="email" placeholder="name@example.com" autocomplete="off"></div>
    <div class="sc-field"><div class="sc-row"><label for="sc-msg">Message</label><span>Optional</span></div><textarea id="sc-msg" rows="4" placeholder="Add a note to go with the recording"></textarea></div>
    <fieldset class="sc-checks"><legend>Add to the email</legend>
      <label class="sc-check"><input type="checkbox" id="sc-sum"><span><b>Summary</b><small>A short recap of what was said</small></span></label>
      <label class="sc-check"><input type="checkbox" id="sc-tr"><span><b>Transcript</b><small>The full text, with timestamps</small></span></label></fieldset>
    <div class="sc-actions"><button type="button" class="sc-go">${MAIL_ICON}<span>Open in Mail</span></button>
      <div class="sc-note"><svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg><span class="sc-notetext"></span></div>
      <p class="sc-status" role="status"></p></div>`;

  function closeShare() {
    if (!shareModal) return;
    document.removeEventListener("keydown", shareModal.onKey);
    shareModal.el.remove();
    const back = shareModal.opener;
    shareModal = null;
    if (back && back.isConnected) back.focus();
  }

  async function openShare(ev) {
    if (shareModal) return;
    const opener = ev && ev.currentTarget;   // read now: the event's target is cleared once we await
    let info;
    try { info = await api(`/api/notes/${id}/share`); } catch (err) { toast(err.message); return; }
    const card = h("section", { class: "share-card", role: "dialog", "aria-modal": "true", "aria-labelledby": "sc-title" });
    card.innerHTML = SHARE_CARD;   // fixed markup above; nothing from the library goes through innerHTML
    const backdrop = h("div", { class: "modal-backdrop", onclick: (e) => { if (e.target === backdrop) closeShare(); } }, card);
    const q = (sel) => card.querySelector(sel);
    q(".sc-name").textContent = info.filename;
    q(".sc-meta").textContent = `Attached as audio · ${info.size_mb} MB`;
    q(".sc-notetext").textContent = info.mail_available
      ? "This opens a draft in Mail with the recording attached. Nothing is sent until you press Send there."
      : "Mail drafts need a Mac with the Mail app, so this can't open one here. Use Download audio instead.";
    if (info.too_big) {
      const warn = q(".sc-warn");
      warn.hidden = false;
      warn.textContent = `This is over ${info.limit_mb} MB, which many email services won't accept. Share a shorter recording, or use Download audio and send it another way.`;
    }
    const go = q(".sc-go"), status = q(".sc-status");
    if (!info.mail_available) go.disabled = true;
    go.addEventListener("click", async () => {
      go.disabled = true; status.textContent = "Opening Mail…";
      try {
        await api(`/api/notes/${id}/share/mail`, { body: { to: q("#sc-to").value, message: q("#sc-msg").value, include_summary: q("#sc-sum").checked, include_transcript: q("#sc-tr").checked } });
        status.textContent = "The draft is open in Mail. Check it there and press Send.";
      } catch (err) { status.textContent = err.message; }
      go.disabled = !info.mail_available ? true : false;
    });
    q(".sc-x").addEventListener("click", closeShare);
    const onKey = (e) => {
      if (e.key === "Escape") { closeShare(); return; }
      if (e.key !== "Tab") return;   // keep keyboard focus inside the card
      const f = [...card.querySelectorAll("button:not([disabled]), input, textarea")];
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", onKey);
    shareModal = { el: backdrop, onKey, opener };
    document.body.appendChild(backdrop);
    q("#sc-to").focus();
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
        h("div", { class: "titlerow" }, h("h1", { class: "ntitle" }, d.title), h("button", { type: "button", class: "ghost", style: "margin-top:8px", onclick: () => { editing = true; render(); } }, "Edit details")),
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
  return () => { closeShare(); audio.pause(); audio.removeAttribute("src"); audio.load(); bus.removeEventListener("audio", onOtherAudio); };
}
