"""Sharing a recording by email.

The app never sends anything itself. It opens a draft in the Mac's Mail app (audio attached, subject and message filled in)
and the person reviews it and presses Send. There are no passwords or mail accounts stored here.
Mail is driven with AppleScript; the values are passed as script arguments, never pasted into the script text.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MAX_EMAIL_MB = 20          # most mail services stop accepting attachments around 20 to 25 MB
KEEP_SHARES_S = 24 * 3600  # copies made for drafts are tidied away after a day
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")

SCRIPT = """on run argv
    set theSubject to item 1 of argv
    set theBody to item 2 of argv
    set thePath to item 3 of argv
    set theTo to item 4 of argv
    set theAttachment to (POSIX file thePath) as alias
    tell application "Mail"
        set m to make new outgoing message with properties {subject:theSubject, content:theBody & return & return, visible:true}
        if theTo is not "" then
            tell m to make new to recipient at end of to recipients with properties {address:theTo}
        end if
        tell content of m
            make new attachment with properties {file name:theAttachment} at after the last paragraph
        end tell
        activate
    end tell
end run
"""


class ShareError(Exception):
    """A problem to show the person in plain words."""


def is_mac() -> bool:
    return sys.platform == "darwin"


def friendly_filename(title: str | None, suffix: str) -> str:
    """A readable file name for the recipient, e.g. 'Baby singing at bedtime.m4a'. Never empty, never a path."""
    name = re.sub(r"[^\w\s\-.,()&']", " ", title or "", flags=re.UNICODE)
    name = " ".join(name.split()).strip(" .")[:60].strip()
    suffix = suffix if re.fullmatch(r"\.[A-Za-z0-9]{1,5}", suffix or "") else ".m4a"
    return f"{name or 'Recording'}{suffix.lower()}"


def clean_address(value: str | None) -> str:
    """The recipient if it looks like one email address, '' if empty; ShareError if it is something else."""
    v = (value or "").strip()
    if not v:
        return ""
    if not _EMAIL.match(v):
        raise ShareError("That doesn't look like an email address. Leave it empty to choose the recipient in Mail.")
    return v


def build_subject(title: str | None) -> str:
    """The email subject. It says what is attached, so a recipient isn't surprised by an audio file:
    'Voice memo: <title>', or just 'Voice memo' when the recording has no title."""
    t = " ".join((title or "").split())
    if t.lower().startswith("voice memo"):
        return t
    return f"Voice memo: {t}" if t else "Voice memo"


def build_body(message: str | None, summary: str | None = None, transcript: str | None = None,
               include_summary: bool = False, include_transcript: bool = False) -> str:
    parts = []
    if (message or "").strip():
        parts.append(message.strip())
    if include_summary and (summary or "").strip():
        parts.append("About this recording:\n" + summary.strip())
    if include_transcript and (transcript or "").strip():
        parts.append("Transcript:\n" + transcript.strip())
    return "\n\n".join(parts)


def size_info(path: Path) -> dict:
    mb = round(path.stat().st_size / (1024 * 1024), 1)
    return {"size_mb": mb, "too_big": mb > MAX_EMAIL_MB, "limit_mb": MAX_EMAIL_MB}


def prepare_copy(src: Path, share_dir: Path, friendly: str) -> Path:
    """Copy the audio under its friendly name (in its own folder, so names never clash) and tidy away old copies."""
    share_dir.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - KEEP_SHARES_S
    for old in share_dir.iterdir():
        try:
            if old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    folder = share_dir / f"{int(time.time() * 1000)}"
    folder.mkdir()
    dest = folder / friendly
    shutil.copy2(src, dest)
    return dest


def run_osascript(script_path: Path, args: list[str], timeout: int = 40) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", str(script_path), *args], capture_output=True, text=True, timeout=timeout)


def explain_failure(stderr: str) -> str:
    low = (stderr or "").lower()
    if "-1743" in low or "not authorized" in low:
        return ("macOS needs your permission first. Open System Settings, then Privacy & Security, then Automation, "
                "and allow Terminal to control Mail. Then try again.")
    if "-1728" in low or "isn't running" in low or "can't get" in low:
        return "Mail couldn't start a message. Open the Mail app once, make sure an email account is set up in it, and try again."
    return "Mail couldn't open the draft: " + " ".join((stderr or "unknown error").split())[:200]


def compose_in_mail(attachment: Path, subject: str, body: str, to: str = "", work_dir: Path | None = None) -> None:
    """Open a Mail draft. Raises ShareError with a plain explanation if it can't."""
    if not is_mac():
        raise ShareError("Mail drafts only work on a Mac with the Mail app. Use Download instead, then attach the file yourself.")
    folder = Path(work_dir) if work_dir else attachment.parent
    script = folder / "compose.applescript"
    script.write_text(SCRIPT)
    try:
        done = run_osascript(script, [subject, body, str(attachment), to])
    except subprocess.TimeoutExpired as exc:
        raise ShareError("Mail took too long to answer. Open the Mail app and try again.") from exc
    except OSError as exc:
        raise ShareError("Couldn't run macOS scripting (osascript).") from exc
    finally:
        try:
            script.unlink()
        except OSError:
            pass
    if done.returncode != 0:
        raise ShareError(explain_failure(done.stderr))
