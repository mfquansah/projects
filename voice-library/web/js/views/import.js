// Import: drop audio files or a folder; they upload, then are processed one by one with live progress.
import { h, api, icons, plural, put, fmtLong } from "../util.js";
import { state, refreshHome, refreshSync, go, ago } from "../core.js";

const AUDIO = /\.(m4a|mp3|wav|aac|caf|qta)$/i;
const SHOW_SYNC_PANEL = false;   // shelved (docs/build-later.md): the sync backend and API still work, only this switch is hidden

// Collect File objects from a drop, including whole folders (dropped folders arrive as directory entries).
async function filesFromDrop(dt) {
  const out = [];
  const walk = async (entry) => {
    if (entry.isFile) await new Promise((res) => entry.file((f) => { out.push(f); res(); }, res));
    else if (entry.isDirectory) {
      const reader = entry.createReader();
      for (;;) {
        const batch = await new Promise((res) => reader.readEntries(res, () => res([])));
        if (!batch.length) break;
        for (const e of batch) await walk(e);
      }
    }
  };
  const entries = [...(dt.items || [])].map((i) => (i.webkitGetAsEntry ? i.webkitGetAsEntry() : null)).filter(Boolean);
  if (entries.length) for (const e of entries) await walk(e);
  else out.push(...dt.files);
  return out;
}

const STATE_TEXT = {
  queued: "Waiting", importing: "Reading the file", titling: "Writing a title and choosing a collection",
  indexing: "Adding it to search", listening: "Listening for sounds",
};

export async function importView({ main }) {
  let timer = null, alive = true;
  const live = h("div", {});
  const drop = h("section", { class: "drop", "aria-label": "Add recordings" });
  const fileInput = h("input", { type: "file", multiple: true, accept: "audio/*,.m4a,.mp3,.wav,.aac,.caf,.qta", class: "sr", tabindex: "-1", onchange: (e) => start([...e.target.files]) });
  const dirInput = h("input", { type: "file", webkitdirectory: true, class: "sr", tabindex: "-1", onchange: (e) => start([...e.target.files]) });

  function paintDrop(text) {
    put(drop, icons.upload(26), h("div", { class: "big-t" }, text || "Drop audio files or a folder here"),
      h("div", { class: "btns" },
        h("button", { type: "button", class: "primary", onclick: () => fileInput.click() }, "Choose files"),
        h("button", { type: "button", class: "ghost", onclick: () => dirInput.click() }, "Choose a folder")),
      h("p", { class: "small", style: "max-width:460px;margin:0" }, "Works with .m4a, .mp3 and .wav. From Voice Memos, drag your recordings out of the app into a folder first, then drop that folder here."),
      fileInput, dirInput);
  }
  paintDrop();
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", async (e) => start(await filesFromDrop(e.dataTransfer)));

  const reportBox = h("div", {});
  async function showReport(jobId) {
    try {
      const r = await api(`/api/import/${jobId}/report`);
      const meta = (await api(`/api/import/${jobId}`)).meta || {};
      const num = (n) => Number(n).toLocaleString();
      const rem = r.remaining;
      const lines = [];
      if (!r.processed) {
        lines.push("Nothing was processed successfully, so there is nothing to estimate yet. See the failures below.");
      } else {
        lines.push(h("p", { style: "margin:0" }, h("strong", {}, "Time: "), `${fmtLong(r.seconds.total)} in total, about ${fmtLong(r.seconds.mean)} per recording (slowest ${fmtLong(r.seconds.max)}).`,
          r.seconds_per_audio_minute ? ` That is about ${plural(Math.round(r.seconds_per_audio_minute), "second")} of work for every minute of audio (${Math.round(r.audio_minutes)} minutes of audio in this batch).` : ""));
        const STEP = { transcribe: "transcribing", enrich: "titling with Claude", index: "indexing", sounds: "listening for sounds", import: "reading files" };
        const st = Object.entries(r.stages || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
        const sum = st.reduce((acc, [, v]) => acc + v, 0);
        if (sum > 0) lines.push(h("p", { style: "margin:0" }, h("strong", {}, "Where the time went: "), st.map(([k, v]) => `${STEP[k] || k} ${Math.round((v / sum) * 100)}%`).join(", "), "."));
        lines.push(h("p", { style: "margin:0" }, h("strong", {}, "Claude: "), `${plural(r.tokens.calls, "call")}, ${num(r.tokens.input)} tokens in and ${num(r.tokens.output)} out`,
          r.cost_usd !== null && r.cost_usd !== undefined ? `, about $${r.cost_usd.toFixed(2)}.` : ". To see dollars, set VL_PRICE_IN_PER_MTOK and VL_PRICE_OUT_PER_MTOK (USD per million tokens, from Anthropic's pricing page) and restart."));
        if (rem) {
          lines.push(h("p", { style: "margin:0" }, h("strong", {}, `The other ${plural(rem.files, "recording")}: `),
            `roughly ${fmtLong(rem.est_seconds)}`, rem.audio_minutes ? ` (about ${num(Math.round(rem.audio_minutes))} minutes of audio)` : "",
            `, using about ${num(rem.est_tokens.input)} input tokens`, rem.est_cost_usd !== null && rem.est_cost_usd !== undefined ? ` and about $${rem.est_cost_usd.toFixed(2)}` : "",
            ". ", h("span", { class: "muted" }, `Estimated from ${rem.basis}. Recordings already in your library are skipped quickly, so the real time may be shorter.`)));
        }
      }
      if (r.failed.length) lines.push(h("p", { style: "margin:0;color:var(--danger)" }, `Failed (${r.failed.length}): ${r.failed.map((f) => `${f.name}: ${f.error}`).join("; ")}`));
      put(reportBox, h("section", { class: "banner report", style: "flex-direction:column;align-items:stretch;gap:12px", "aria-label": "Batch results" },
        h("h2", { class: "eyebrow ul", style: "align-self:flex-start" }, `Batch results · ${plural(r.processed, "recording")} processed`),
        lines,
        h("div", { class: "actions" },
          rem && rem.files ? h("button", { type: "button", class: "primary", onclick: () => { put(reportBox); startFolder({ path: meta.folder }); } }, `Import the remaining ${rem.files}`) : null,
          h("button", { type: "button", class: "ghost", onclick: () => put(reportBox) }, "Close"))));
    } catch (_) { put(reportBox); }
  }
  const dropNote = h("div", { class: "sysnote", style: "display:none;margin:0", role: "status" });
  const say = (text) => { dropNote.textContent = text || ""; dropNote.style.display = text ? "" : "none"; };

  // Import straight from this computer: no uploading, files are read where they are and never changed.
  const vmBox = h("div", {});
  const pathIn = h("input", { class: "edit", placeholder: "/Users/you/Desktop/my-recordings", "aria-label": "Folder path on this computer", autocomplete: "off" });
  async function startFolder(body) {
    say(""); put(reportBox);
    try { const r = await api("/api/import/folder", { body }); poll(r.job_id); }
    catch (err) { say(err.message); }
  }
  async function loadSources() {
    try {
      const vm = (await api("/api/import/sources")).voice_memos;
      vmInfo = vm;
      if (SHOW_SYNC_PANEL) paintSync();
      put(vmBox, vm.found
        ? h("div", { style: "display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 20px" },
            h("div", { style: "flex:1 1 280px" }, h("strong", {}, "Voice Memos"),
              h("div", { class: "muted", style: "font-size:14px" }, `${plural(vm.count, "recording")} found on this computer. They are read where they are and never changed.${state.settings?.max_minutes ? ` Recordings longer than ${state.settings.max_minutes} minutes (usually meetings) are skipped.` : ""}`)),
            h("div", { class: "actions" },
              h("button", { type: "button", class: "ghost", title: "Imports your newest recordings first and reports how long it took and what Claude cost, so you can estimate the whole library", onclick: () => startFolder({ source: "voice_memos", newest: Math.min(25, vm.count) }) }, `Try a test batch (${Math.min(25, vm.count)} newest)`),
              h("button", { type: "button", class: "ghost", title: "Imports the next 100 newest recordings that aren't in the library yet, and reports time and Claude usage when done", onclick: () => startFolder({ source: "voice_memos", newest: Math.min(100, vm.count) }) }, "Import the next 100"),
              h("button", { type: "button", class: "primary", onclick: () => startFolder({ source: "voice_memos" }) }, `Import all ${vm.count}`)))
        : h("div", { class: "sysnote", style: "margin:0" }, vm.problem));
    } catch (_) { vmBox.replaceChildren(); }
  }
  // Keep in sync: explicit opt-in, because the first sync can import a whole library
  const syncBox = h("div", {});
  let vmInfo = null;
  async function setSync(body) {
    try { await api("/api/sync/settings", { body }); await refreshSync(); paintSync(); say(""); }
    catch (err) { say(err.message); }
  }
  function paintSync(confirming = false) {
    const sy = state.sync;
    if (!sy || !sy.available) { put(syncBox); return; }
    if (sy.enabled) {
      const last = sy.last;
      put(syncBox, h("div", { class: "banner", style: "gap:10px 20px" },
        h("p", {}, h("strong", {}, "Automatic sync is on."), " ",
          sy.problem ? sy.problem
            : (sy.pending ? `Importing ${plural(sy.pending, "recording")}…` : (last ? `Checked ${ago(last.at)}, ${last.new ? plural(last.new, "new recording") + " found" : "nothing new"}. ` : "Starting…")),
          last && last.placeholders ? ` ${plural(last.placeholders, "recording")} still in iCloud, not on this Mac yet.` : "",
          sy.changed ? ` ${plural(sy.changed, "recording")} changed in Voice Memos after import (not re-imported).` : ""),
        h("div", { class: "actions" },
          h("button", { type: "button", class: "ghost", onclick: async () => { await api("/api/sync/run", { method: "POST", body: {} }); await refreshSync(); paintSync(); } }, "Sync now"),
          h("button", { type: "button", class: "ghost", onclick: () => setSync({ enabled: false }) }, "Turn off"))));
      return;
    }
    const n = vmInfo && vmInfo.found ? vmInfo.count : null;
    if (confirming && n !== null) {
      put(syncBox, h("div", { class: "banner", style: "gap:12px 20px" },
        h("p", {}, h("strong", {}, `Import ${plural(n, "recording")} now, then new ones as they arrive.`),
          " Each is transcribed on this Mac and its text is sent to Claude to write a title, so a big library can take hours. Keep this app running. You can turn it off any time."),
        h("div", { class: "actions" },
          h("button", { type: "button", class: "primary", onclick: () => setSync({ enabled: true }) }, `Turn on and import ${n}`),
          h("button", { type: "button", class: "ghost", onclick: () => paintSync() }, "Cancel"))));
      return;
    }
    put(syncBox, h("div", { style: "display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px 20px" },
      h("div", { style: "flex:1 1 280px" }, h("strong", {}, "Keep in sync with Voice Memos"),
        h("div", { class: "muted", style: "font-size:14px" }, "Off. Turn it on to import new recordings automatically (checked every 10 minutes).")),
      h("button", { type: "button", class: "ghost", disabled: n === null, title: n === null ? "Voice Memos can't be reached yet (see above)" : "", onclick: () => paintSync(true) }, "Turn on…")));
  }
  const local = h("section", { "aria-label": "Import from this computer", style: "display:flex;flex-direction:column;gap:16px" },
    h("h2", { class: "eyebrow ul", style: "align-self:flex-start" }, "From this computer"),
    SHOW_SYNC_PANEL ? syncBox : null,
    vmBox,
    h("form", { style: "display:flex;flex-wrap:wrap;gap:10px", onsubmit: (e) => { e.preventDefault(); startFolder({ path: pathIn.value }); } },
      h("div", { style: "flex:1 1 280px" }, pathIn),
      h("button", { type: "submit", class: "ghost" }, "Import this folder")),
    h("p", { class: "small", style: "margin:0" }, "Tip: dragging straight out of the Voice Memos app doesn't work in a browser. Drag the recordings into a Finder folder first and import that folder here, or use the Voice Memos option above once macOS gives this app access."));

  main.append(h("div", { class: "col", style: "gap:28px" },
    h("header", { style: "display:flex;flex-direction:column;gap:8px" }, h("h1", { class: "h1" }, "Import"),
      h("p", { class: "muted", style: "margin:0" }, "Add voice notes you already have. Each one is transcribed, titled and sorted into a collection, then checked for sounds like a baby laughing.")),
    drop, dropNote, local, live, reportBox));

  function start(files) {
    say("");
    if (!files.length) {
      say("Nothing came through. Browsers can't receive files dragged straight out of Voice Memos. Use “Import” under Voice Memos below, or drag the recordings into a Finder folder first and drop that folder here.");
      return;
    }
    const audio = files.filter((f) => AUDIO.test(f.name));
    if (!audio.length) { say("None of those were audio files (I look for .m4a, .mp3, .wav, .aac and .caf)."); return; }
    paintDrop(`Uploading ${plural(audio.length, "recording")}…`);
    const fd = new FormData();
    for (const f of audio) { fd.append("files", f, f.name); fd.append("modified", String(f.lastModified || 0)); }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/import");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) drop.querySelector(".big-t").textContent = `Uploading ${plural(audio.length, "recording")}… ${Math.round((e.loaded / e.total) * 100)}%`; };
    xhr.onload = () => {
      let body = {}; try { body = JSON.parse(xhr.responseText); } catch (_) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) { paintDrop(); poll(body.job_id, body.rejected || []); }
      else paintDrop(body.detail || "That upload didn't work. Please try again.");
    };
    xhr.onerror = () => paintDrop("The upload failed. Is the app still running?");
    xhr.send(fd);
  }

  function row(f) {
    let status;
    if (f.state === "done") status = h("div", { style: "display:flex;gap:10px;align-items:flex-start" }, h("span", { style: "color:var(--accent);margin-top:3px" }, icons.check(16)),
      h("span", {}, "Saved as ", h("a", { class: "link", href: `#/note/${f.note_id}` }, f.title), f.category ? h("span", { class: "muted" }, ` in ${f.category}`) : null));
    else if (f.state === "duplicate") status = h("span", { class: "muted" }, "Already in your library", f.title ? [": ", h("a", { class: "link", href: `#/note/${f.note_id}` }, f.title)] : null);
    else if (f.state === "error") status = h("span", {}, f.error || "Something went wrong");
    else if (f.state === "transcribing") status = h("div", {}, `Transcribing · ${f.pct}%`, h("div", { class: "mini" }, h("div", { style: `width:${f.pct}%` })));
    else status = h("span", { class: "muted" }, STATE_TEXT[f.state] || f.state);
    return h("div", { class: "frow" }, h("div", { class: "fname" }, f.name), h("div", { class: `fstate${f.state === "error" ? " err" : ""}` }, status));
  }

  function paint(snap, rejected) {
    const finishedCount = snap.done + snap.errors;
    put(live, h("section", { "aria-label": "Progress" },
      h("div", { style: "display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:8px 16px" },
        h("h2", { style: "margin:0;font-size:15px;font-weight:600" }, snap.finished ? `Imported ${plural(snap.total, "recording")}` : `Importing ${plural(snap.total, "recording")}`)),
      h("div", { class: "muted", style: "font-size:14px" }, [`${snap.done} done`, snap.working ? `${snap.working} in progress` : null, snap.waiting ? `${snap.waiting} waiting` : null, snap.errors ? `${snap.errors} failed` : null].filter(Boolean).join(" · ")),
      h("div", { class: "meter", role: "progressbar", "aria-label": "Import progress", "aria-valuemin": "0", "aria-valuemax": String(snap.total), "aria-valuenow": String(finishedCount) }, h("div", { style: `width:${snap.total ? (finishedCount / snap.total) * 100 : 0}%` })),
      snap.meta && snap.meta.skipped_long ? h("div", { class: "sysnote" }, `${plural(snap.meta.skipped_long, "recording")} not imported because ${snap.meta.skipped_long === 1 ? "it is" : "they are"} longer than ${snap.meta.max_minutes} minutes.`) : null,
      rejected.length ? h("div", { class: "sysnote" }, `Skipped: ${rejected.map((r) => `${r.name} (${r.reason})`).join("; ")}`) : null,
      h("div", {}, snap.files.map(row)),
      snap.finished ? banner(snap) : null));
  }
  function banner(snap) {
    const n = state.home?.attention_count || 0;
    return h("div", { class: "banner", style: "margin-top:20px" },
      h("p", {}, n ? [h("strong", {}, `${plural(n, "thing")} to check.`), " Look over the suggested titles and collections before they settle into your library."]
        : [h("strong", {}, "All imported."), snap.errors ? " Some files failed; their reasons are above." : " Everything is in your library and searchable."]),
      h("button", { type: "button", class: "primary", onclick: () => go(n ? "#/attention" : "#/") }, n ? "Review suggestions" : "Open the library"));
  }

  async function poll(jobId, rejected = []) {
    clearTimeout(timer);
    try {
      const snap = await api(`/api/import/${jobId}`);
      if (!alive) return;
      if (snap.finished) { await refreshHome(); paint(snap, rejected); if (snap.meta && snap.meta.batch) showReport(snap.id); return; }
      paint(snap, rejected);
      timer = setTimeout(() => poll(jobId, rejected), 1000);
    } catch (err) { live.replaceChildren(h("div", { class: "sysnote" }, err.message)); }
  }

  loadSources();
  if (SHOW_SYNC_PANEL) paintSync();
  // coming back to this screen: show the latest import (and keep following it if it's still running)
  try { const r = await api("/api/import/latest"); if (r.job) poll(r.job.id); } catch (_) { /* no import manager: nothing to show */ }
  return () => { alive = false; clearTimeout(timer); };
}
