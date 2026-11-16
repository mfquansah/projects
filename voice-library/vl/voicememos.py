"""Find and list recordings in a folder on this computer, including the Mac's own Voice Memos library.

Nothing here modifies or deletes anything: files are only read (and copied into the library by the importer).
macOS protects the Voice Memos folder; if access is blocked we say exactly what to change instead of failing quietly.
"""
from __future__ import annotations

import os
from pathlib import Path

from vl.ingest.importer import AUDIO_EXTS

# Newer macOS keeps the library in a group container; older versions use Application Support.
CANDIDATES = [
    "~/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings",
    "~/Library/Application Support/com.apple.voicememos/Recordings",
]
MAX_FILES = 5000

PERMISSION_HELP = ("macOS is blocking access to Voice Memos. Open System Settings, then Privacy & Security, then Full Disk Access, "
                   "turn it on for Terminal (or whichever app you started this from), and restart Voice Library. "
                   "Or drag your recordings out of Voice Memos into a Finder folder and import that folder instead.")


def audio_files(folder: Path, limit: int = MAX_FILES) -> list[Path]:
    """Audio files under `folder` (recursive), sorted. Raises PermissionError if macOS blocks the folder."""
    found: list[Path] = []
    stack = [folder]
    while stack and len(found) < limit:
        d = stack.pop()
        with os.scandir(d) as it:  # PermissionError propagates on purpose
            for e in it:
                if e.name.startswith("."):
                    continue
                if e.is_dir(follow_symlinks=False):
                    stack.append(Path(e.path))
                elif e.is_file() and Path(e.name).suffix.lower() in AUDIO_EXTS:
                    found.append(Path(e.path))
    return sorted(found)[:limit]


def find_voice_memos(candidates: list[str] | None = None) -> dict:
    """{'found': bool, 'path': str|None, 'count': int, 'problem': str|None}. Never raises."""
    blocked = None
    for c in (candidates or CANDIDATES):
        p = Path(c).expanduser()
        try:
            if not p.exists():
                continue
            files = audio_files(p)
            return {"found": True, "path": str(p), "count": len(files), "problem": None}
        except PermissionError:
            blocked = str(p)
        except OSError:
            continue
    if blocked:
        return {"found": False, "path": blocked, "count": 0, "problem": PERMISSION_HELP}
    return {"found": False, "path": None, "count": 0,
            "problem": "I couldn't find the Voice Memos library on this computer. Drag your recordings into a Finder folder and import that folder."}


def icloud_placeholders(folder: Path) -> int:
    """Recordings that exist in iCloud but aren't downloaded to this Mac yet (macOS shows them as hidden '.name.icloud' stubs)."""
    n = 0
    stack = [folder]
    while stack:
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False) and not e.name.startswith("."):
                        stack.append(Path(e.path))
                    elif e.name.startswith(".") and e.name.endswith(".icloud"):
                        n += 1
        except OSError:
            continue
    return n
