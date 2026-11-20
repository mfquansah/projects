import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vl import share
from vl.api.main import create_app
from vl.db import make_session_factory
from vl.ingest.importer import import_one
from vl.pipeline import ProcessResult, process_note

from tests.conftest import FakeEmbedder, FakeEnricher, FakeTranscriber


# ---------- pure helpers ----------

def test_friendly_filename_is_readable_safe_and_never_empty():
    assert share.friendly_filename("Baby singing at bedtime", ".M4A") == "Baby singing at bedtime.m4a"
    assert share.friendly_filename("../../etc/passwd", ".m4a") == "etc passwd.m4a"        # no path tricks
    assert share.friendly_filename("   ", ".m4a") == "Recording.m4a"
    assert share.friendly_filename(None, "m4a") == "Recording.m4a"                       # a bad suffix falls back
    assert len(share.friendly_filename("x" * 300, ".m4a")) <= 64


def test_clean_address():
    assert share.clean_address("  ama@example.com ") == "ama@example.com"
    assert share.clean_address("") == "" and share.clean_address(None) == ""
    for bad in ("ama", "a b@c.com", "a@b", "a@b.com, c@d.com"):
        with pytest.raises(share.ShareError):
            share.clean_address(bad)


def test_build_body_only_includes_what_was_asked_for():
    assert share.build_body("Listen to this!", "A sum", "Full text") == "Listen to this!"
    full = share.build_body("Hi", "A sum", "Full text", True, True)
    assert full == "Hi\n\nAbout this recording:\nA sum\n\nTranscript:\nFull text"
    assert share.build_body(None, "s", "t", True, False) == "About this recording:\ns"
    assert share.build_body("  ", None, None, True, True) == ""


def test_prepare_copy_names_the_copy_and_tidies_old_ones(tmp_path):
    src = tmp_path / "abc123.m4a"
    src.write_bytes(b"audio")
    shares = tmp_path / "shares"
    old = shares / "1"
    old.mkdir(parents=True)
    (old / "x.m4a").write_bytes(b"old")
    long_ago = time.time() - 3 * 24 * 3600
    os.utime(old, (long_ago, long_ago))
    dest = share.prepare_copy(src, shares, "Baby singing.m4a")
    assert dest.name == "Baby singing.m4a" and dest.read_bytes() == b"audio"
    assert not old.exists()                       # a copy from days ago was removed
    assert src.exists()                           # the library's file is untouched


# ---------- Mail (osascript faked: it only exists on a Mac) ----------

def test_compose_passes_values_as_arguments_not_script_text(tmp_path, monkeypatch):
    seen = {}

    def fake(script_path, args, timeout=40):
        seen["args"], seen["script"] = args, Path(script_path).read_text()
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(share, "is_mac", lambda: True)
    monkeypatch.setattr(share, "run_osascript", fake)
    att = tmp_path / "Baby singing.m4a"
    att.write_bytes(b"x")
    nasty = 'He said "hi" \\ and `rm -rf` $(x)'
    share.compose_in_mail(att, nasty, "line1\nline2", "ama@example.com")
    assert seen["args"] == [nasty, "line1\nline2", str(att), "ama@example.com"]
    assert nasty not in seen["script"] and "on run argv" in seen["script"]
    assert not (tmp_path / "compose.applescript").exists()       # the temporary script is removed


@pytest.mark.parametrize("stderr,expect", [
    ("execution error: Not authorized to send Apple events to Mail. (-1743)", "Automation"),
    ("Mail got an error: Can't get account (-1728)", "email account"),
    ("something odd happened", "something odd happened"),
])
def test_failures_are_explained(tmp_path, monkeypatch, stderr, expect):
    monkeypatch.setattr(share, "is_mac", lambda: True)
    monkeypatch.setattr(share, "run_osascript", lambda *a, **k: subprocess.CompletedProcess([], 1, "", stderr))
    att = tmp_path / "a.m4a"
    att.write_bytes(b"x")
    with pytest.raises(share.ShareError) as e:
        share.compose_in_mail(att, "s", "b")
    assert expect in str(e.value)


def test_timeout_and_not_a_mac(tmp_path, monkeypatch):
    att = tmp_path / "a.m4a"
    att.write_bytes(b"x")
    monkeypatch.setattr(share, "is_mac", lambda: False)
    with pytest.raises(share.ShareError, match="Mac"):
        share.compose_in_mail(att, "s", "b")
    monkeypatch.setattr(share, "is_mac", lambda: True)

    def slow(*a, **k):
        raise subprocess.TimeoutExpired("osascript", 40)

    monkeypatch.setattr(share, "run_osascript", slow)
    with pytest.raises(share.ShareError, match="too long"):
        share.compose_in_mail(att, "s", "b")


# ---------- API ----------

@pytest.fixture
def app_env(tmp_path):
    factory = make_session_factory(tmp_path / "t.db")
    audio = tmp_path / "audio"
    src = tmp_path / "20261101 100000.m4a"
    src.write_bytes(b"baby singing a lullaby")
    with factory() as s:
        note, _ = import_one(s, src, audio)
        process_note(s, note, FakeTranscriber(), FakeEnricher(), FakeEmbedder(), ProcessResult())
        nid, copy = note.id, Path(note.path)
    client = TestClient(create_app(factory, embedder=FakeEmbedder(), audio_root=audio, share_dir=tmp_path / "shares"))
    client.factory = factory
    return client, nid, copy, tmp_path


def test_download_has_a_readable_name(app_env):
    c, nid, copy, _ = app_env
    r = c.get(f"/api/notes/{nid}/download")
    assert r.status_code == 200 and r.content == b"baby singing a lullaby"
    disp = r.headers["content-disposition"]
    assert "attachment" in disp and ".m4a" in disp and copy.name not in disp
    assert c.get("/api/notes/999/download").status_code == 404


def test_download_refuses_files_outside_the_audio_folder(app_env):
    c, nid, _, tmp = app_env
    from vl.db import Note
    outside = tmp / "secret.txt"
    outside.write_text("private")
    with c.factory() as s:
        s.get(Note, nid).path = str(outside)
        s.commit()
    assert c.get(f"/api/notes/{nid}/download").status_code == 403
    assert c.post(f"/api/notes/{nid}/share/mail", json={}).status_code == 403


def test_share_info_and_mail_draft(app_env, monkeypatch):
    c, nid, _, tmp = app_env
    info = c.get(f"/api/notes/{nid}/share").json()
    assert info["filename"].endswith(".m4a") and info["too_big"] is False and info["size_mb"] >= 0
    calls = []
    monkeypatch.setattr(share, "is_mac", lambda: True)
    monkeypatch.setattr(share, "run_osascript", lambda script, args, timeout=40: calls.append(args) or subprocess.CompletedProcess([], 0, "", ""))
    r = c.post(f"/api/notes/{nid}/share/mail", json={"to": "ama@example.com", "message": "Listen!", "include_transcript": True})
    assert r.status_code == 200 and r.json()["ok"] is True
    subject, body, path, to = calls[0]
    assert to == "ama@example.com" and body.startswith("Listen!") and "Transcript:" in body and "baby singing" in body
    assert Path(path).name == r.json()["filename"] and Path(path).read_bytes() == b"baby singing a lullaby"
    assert str(tmp / "shares") in path                                    # copies live in the share folder


def test_mail_draft_errors_are_plain(app_env, monkeypatch):
    c, nid, _, _ = app_env
    monkeypatch.setattr(share, "is_mac", lambda: False)
    r = c.post(f"/api/notes/{nid}/share/mail", json={})
    assert r.status_code == 400 and "Download" in r.json()["detail"]
    monkeypatch.setattr(share, "is_mac", lambda: True)
    bad = c.post(f"/api/notes/{nid}/share/mail", json={"to": "not an address"})
    assert bad.status_code == 400 and "email address" in bad.json()["detail"]
    assert c.post("/api/notes/999/share/mail", json={}).status_code == 404
