"""Small personal settings kept in ~/VoiceLibrary/profile.json (never in the code or the repository)."""
from __future__ import annotations

import json
from pathlib import Path

MAX_NAME = 40


def clean_name(value) -> str:
    """A display name: one line, trimmed, at most MAX_NAME characters. Anything unusable becomes ''."""
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:MAX_NAME]


def load_name(home: Path) -> str:
    try:
        return clean_name(json.loads((Path(home) / "profile.json").read_text()).get("name"))
    except (OSError, ValueError, AttributeError):
        return ""


def save_name(home: Path, name: str) -> str:
    name = clean_name(name)
    path = Path(home) / "profile.json"
    try:
        data = json.loads(path.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["name"] = name
    path.write_text(json.dumps(data, indent=2))
    return name
