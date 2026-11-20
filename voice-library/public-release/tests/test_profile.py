from fastapi.testclient import TestClient

from vl.api.main import create_app
from vl.db import make_session_factory
from vl.profile import clean_name, load_name, save_name


def test_name_is_saved_cleaned_and_loaded(tmp_path):
    assert load_name(tmp_path) == ""                          # nothing saved yet
    assert save_name(tmp_path, "  Ama \n ") == "Ama"
    assert load_name(tmp_path) == "Ama"
    assert save_name(tmp_path, "") == "" and load_name(tmp_path) == ""   # --name "" removes it
    assert len(clean_name("x" * 200)) == 40 and clean_name(None) == ""


def test_broken_profile_file_is_ignored(tmp_path):
    (tmp_path / "profile.json").write_text("{not json")
    assert load_name(tmp_path) == ""
    assert save_name(tmp_path, "Ama") == "Ama"                # and it can be overwritten


def test_settings_carry_the_name(tmp_path):
    c = TestClient(create_app(make_session_factory(tmp_path / "t.db"), display_name="Ama"))
    assert c.get("/api/settings").json()["name"] == "Ama"
