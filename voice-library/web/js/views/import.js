// Import: drop audio files or a folder; they upload, then are processed one by one with live progress.
import { h, api, icons, plural, put } from "../util.js";
import { state, refreshHome, go } from "../core.js";

const AUDIO = /\.(m4a|mp3|wav|aac|caf|qta)$/i;

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

  main.append(h("div", { class: "col", style: "gap:32px" },
    h("header", { style: "display:flex;flex-direction:column;gap:8px" }, h("h1", { class: "h1" }, "Import"),
      h("p", { class: "muted", style: "margin:0" }, "Add voice notes you already have. Each one is transcribed, titled and sorted into a collection, then checked for sounds like a baby laughing.")),
    drop, live));

  function start(files) {
    const audio = files.filter((f) => AUDIO.test(f.name));
    if (!audio.length) { paintDrop(files.length ? "None of those were audio files" : "Drop audio files or a folder here"); return; }
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
      if (snap.finished) { await refreshHome(); paint(snap, rejected); return; }
      paint(snap, rejected);
      timer = setTimeout(() => poll(jobId, rejected), 1000);
    } catch (err) { live.replaceChildren(h("div", { class: "sysnote" }, err.message)); }
  }

  // coming back to this screen: show the latest import (and keep following it if it's still running)
  try { const r = await api("/api/import/latest"); if (r.job) poll(r.job.id); } catch (_) { /* no import manager: nothing to show */ }
  return () => { alive = false; clearTimeout(timer); };
}
