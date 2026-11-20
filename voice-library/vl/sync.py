"""Automatic sync: keep the library up to date with a folder on this computer (normally Voice Memos).

One-way and read-only: new recordings in the folder are imported; nothing is ever written to, changed, or deleted there.
Design choices (each guards against a real failure):
 - It remembers (size, modified time) per file, so a check every few minutes doesn't re-read hundreds of recordings.
 - A file counts as "seen" only after it was imported successfully; failures are retried, but only a few times.
 - A file that CHANGED after being imported (e.g. trimmed in Voice Memos) is reported, not re-imported as a duplicate note.
 - Turning sync on is explicit (the first run can import a whole library, which takes hours): it never starts by itself.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path

from vl.jobs import DONE, DUPLICATE, REMOVED
from vl.batch import split_by_length
from vl.voicememos import PERMISSION_HELP, audio_files, find_voice_memos, icloud_placeholders, newest_first

MAX_FAILURES = 3
DEFAULT_INTERVAL_MIN = 10


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class SyncManager:
    def __init__(self, import_manager, state_dir: Path, source_resolver=None, poll_seconds: float | None = None,
                 max_minutes: float | None = None) -> None:
        """`source_resolver(source) -> (folder|None, problem|None)`. Default: 'voice_memos' or a folder path.

        `poll_seconds` overrides the interval (tests only).
        """
        self._im = import_manager
        self._max_minutes = max_minutes  # recordings longer than this are left alone (None/0 = no limit)
        self._durations: dict = {}
        self._dir = Path(state_dir)
        self._resolve = source_resolver or self._default_resolver
        self._poll_override = poll_seconds
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._inflight: dict[str, list] = {}
        self._last: dict | None = None
        self._problem: str | None = None
        self.settings = {"enabled": False, "interval_min": DEFAULT_INTERVAL_MIN, "source": "voice_memos"}
        self.state = {"seen": {}, "failures": {}, "changed": []}
        self._load()

    # ---------- persistence ----------
    def _load(self) -> None:
        for name, target in (("sync_settings.json", self.settings), ("sync_state.json", self.state)):
            try:
                data = json.loads((self._dir / name).read_text())
                if isinstance(data, dict):
                    target.update({k: v for k, v in data.items() if k in target})
            except (OSError, ValueError):
                pass

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            (self._dir / "sync_settings.json").write_text(json.dumps(self.settings))
            (self._dir / "sync_state.json").write_text(json.dumps(self.state))
        except OSError:
            pass

    @staticmethod
    def _default_resolver(source: str):
        if source == "voice_memos":
            info = find_voice_memos()
            return (Path(info["path"]) if info["found"] else None), info["problem"]
        p = Path(source).expanduser()
        return (p, None) if p.is_dir() else (None, f"'{p}' isn't a folder on this computer.")

    # ---------- public ----------
    def status(self) -> dict:
        with self._lock:
            return {**self.settings, "pending": len(self._inflight), "problem": self._problem, "last": self._last,
                    "changed": len(self.state["changed"])}

    def set_settings(self, enabled: bool | None = None, interval_min: int | None = None) -> dict:
        with self._lock:
            if interval_min is not None:
                if not 1 <= int(interval_min) <= 1440:
                    raise ValueError("The interval must be between 1 minute and 24 hours.")
                self.settings["interval_min"] = int(interval_min)
            if enabled is not None:
                self.settings["enabled"] = bool(enabled)
            self._save()
        if self.settings["enabled"]:
            self.start()
            self._wake.set()  # run a check right away
        return self.status()

    def trigger(self) -> None:
        """Ask for a check now (runs on the background thread, never blocks the caller)."""
        self.start()
        self._wake.set()

    def start(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._loop, name="vl-sync", daemon=True)
                self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ---------- the check ----------
    def run_once(self) -> dict:
        """One check: find new recordings and hand them to the importer. Returns what it found. Never raises."""
        found = {"at": _now(), "files": 0, "new": 0, "changed": 0, "placeholders": 0, "too_long": 0, "problem": None}
        try:
            folder, problem = self._resolve(self.settings["source"])
            if folder is None:
                found["problem"] = problem or "The folder to sync isn't available."
            else:
                files = newest_first(audio_files(folder))  # newest first: recent recordings become searchable first
                files, too_long = split_by_length(files, self._max_minutes, self._durations)
                found["files"] = len(files)
                found["too_long"] = len(too_long)
                if self.settings["source"] == "voice_memos":
                    found["placeholders"] = icloud_placeholders(folder)
                items = []
                with self._lock:
                    for p in files:
                        key = str(p)
                        try:
                            st = p.stat()
                        except OSError:
                            continue
                        sig = [st.st_size, int(st.st_mtime)]
                        if key in self._inflight or self.state["failures"].get(key, 0) >= MAX_FAILURES:
                            continue
                        if key in self.state["seen"]:
                            if self.state["seen"][key] != sig and key not in self.state["changed"]:
                                self.state["changed"].append(key)  # edited since import: reported, not re-imported
                            continue
                        self._inflight[key] = sig
                        items.append((p.name, p, dt.datetime.fromtimestamp(st.st_mtime), False))
                    found["new"] = len(items)
                    found["changed"] = len(self.state["changed"])
                if items:
                    self._im.submit(items)
        except PermissionError:
            found["problem"] = PERMISSION_HELP
        except Exception as exc:  # noqa: BLE001 - the loop must survive anything
            found["problem"] = f"Sync problem: {type(exc).__name__}: {exc}"
        with self._lock:
            self._last, self._problem = found, found["problem"]
            self._save()
        return found

    def on_file_done(self, f) -> None:
        """Called by the importer after each file: remember successes, count failures."""
        key = str(f.path)
        with self._lock:
            sig = self._inflight.pop(key, None)
            if sig is None:
                return
            if f.state in (DONE, DUPLICATE, REMOVED):
                self.state["seen"][key] = sig
                self.state["failures"].pop(key, None)
            else:
                self.state["failures"][key] = self.state["failures"].get(key, 0) + 1
            self._save()

    # ---------- thread ----------
    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.settings["enabled"]:
                self.run_once()
            wait = self._poll_override if self._poll_override is not None else self.settings["interval_min"] * 60
            self._wake.wait(timeout=wait)
            self._wake.clear()
