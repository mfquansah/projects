// State and actions shared by every screen (kept free of screen code so screens can import it without cycles).
import { $, api, emit, toast } from "./util.js";

export const state = { home: null, settings: null, sync: null };

export async function refreshHome() {
  state.home = await api("/api/home");
  emit("refresh");
  return state.home;
}

export async function refreshSync() {
  try { state.sync = await api("/api/sync"); } catch (_) { state.sync = null; }
  emit("refresh");
  return state.sync;
}

export function ago(iso) {
  if (!iso) return "";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const go = (hash) => { location.hash = hash; };

// The "new collection" dialog, optionally started from a tag.
export function collectionDialog({ fromTag = null, onDone = null } = {}) {
  const dlg = $("#dlg"), name = $("#dlgName"), err = $("#dlgErr"), form = $("#dlgForm");
  $("#dlgTitle").textContent = fromTag ? `New collection from the tag “${fromTag}”` : "New collection";
  name.value = fromTag ? fromTag.charAt(0).toUpperCase() + fromTag.slice(1) : "";
  err.textContent = "";
  $("#dlgCancel").onclick = () => dlg.close();
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/categories", { body: { name: name.value, from_tag: fromTag } });
      dlg.close();
      toast(r.moved ? `Created “${r.category}” and moved ${r.moved} recording${r.moved === 1 ? "" : "s"} into it.` : `Created “${r.category}”.`);
      await refreshHome();
      if (onDone) onDone(r);
    } catch (ex) { err.textContent = ex.message; }
  };
  dlg.showModal(); name.focus(); name.select();
}
