import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

from pdfunlocker.cli import installer, personal_cli
from pdfunlocker.profiles import manager, store


def make_installed_profile(tmp_path, monkeypatch):
    app_data = tmp_path / "personal-app"
    database_dir = app_data / "database"
    profiles_dir = app_data / "profiles"
    config_path = app_data / "config.json"

    database_dir.mkdir(parents=True)
    profiles_dir.mkdir(parents=True)

    config = {
        "setup_complete": True,
        "edition": "personal",
        "app_data_directory": str(app_data),
        "database_directory": str(database_dir),
        "profiles_directory": str(profiles_dir),
        "profile_id": 1,
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")

    monkeypatch.setattr(
        installer, "find_installation_config", lambda: config_path
    )

    old_db = store.DB_PATH
    store.DB_PATH = database_dir / "profiles.sqlite3"
    try:
        store.initialize()
        manager.save_env(
            profiles_dir / "profile01.env",
            {
                "PROFILE_ID": "1",
                "PROFILE_NAME": "Personal",
                "FIRST_NAME": "RUPESH",
            },
        )
    finally:
        store.DB_PATH = old_db

    return config_path, config, database_dir, profiles_dir


def test_profile_context_uses_personal_paths_and_restores_globals(
    tmp_path, monkeypatch
):
    _, config, database_dir, profiles_dir = make_installed_profile(
        tmp_path, monkeypatch
    )
    old_db = store.DB_PATH
    old_profiles = manager.PROFILES_DIR
    old_sequence = manager.SEQUENCE_FILE

    with personal_cli._personal_profile_context(config) as (
        _manager, _store, profile_id, profile_path
    ):
        assert store.DB_PATH == database_dir / "profiles.sqlite3"
        assert manager.PROFILES_DIR == profiles_dir
        assert manager.SEQUENCE_FILE == profiles_dir / "profile_sequence.txt"
        assert profile_id == 1
        assert profile_path == profiles_dir / "profile01.env"

    assert store.DB_PATH == old_db
    assert manager.PROFILES_DIR == old_profiles
    assert manager.SEQUENCE_FILE == old_sequence


def test_profile_show_uses_personal_database(tmp_path, monkeypatch, capsys):
    _, _, database_dir, _ = make_installed_profile(tmp_path, monkeypatch)
    old_db = store.DB_PATH

    personal_cli.command_profile_show(Namespace())

    output = capsys.readouterr().out
    assert "RUPESH" in output
    assert store.DB_PATH == old_db
    assert (database_dir / "profiles.sqlite3").is_file()


def test_profile_edit_calls_existing_manager(tmp_path, monkeypatch):
    _, _, _, _ = make_installed_profile(tmp_path, monkeypatch)
    calls = []

    monkeypatch.setattr(
        manager, "modify_profile",
        lambda profile_id: calls.append(profile_id),
    )

    personal_cli.command_profile_edit(Namespace())
    assert calls == [1]


def test_profile_reset_requires_exact_confirmation(
    tmp_path, monkeypatch, capsys
):
    _, _, database_dir, _ = make_installed_profile(tmp_path, monkeypatch)
    old_db = store.DB_PATH

    with patch("builtins.input", return_value="no"):
        personal_cli.command_profile_reset(Namespace())

    assert "cancelled" in capsys.readouterr().out.lower()

    store.DB_PATH = database_dir / "profiles.sqlite3"
    try:
        values = store.load_profile(1)
    finally:
        store.DB_PATH = old_db

    assert values["FIRST_NAME"] == "RUPESH"


def test_profile_reset_clears_values_and_preserves_identity(
    tmp_path, monkeypatch, capsys
):
    _, _, database_dir, profiles_dir = make_installed_profile(
        tmp_path, monkeypatch
    )
    old_db = store.DB_PATH

    with patch("builtins.input", return_value="RESET"):
        personal_cli.command_profile_reset(Namespace())

    output = capsys.readouterr().out
    assert "reset" in output.lower()

    store.DB_PATH = database_dir / "profiles.sqlite3"
    try:
        values = store.load_profile(1)
    finally:
        store.DB_PATH = old_db

    assert values == {
        "PROFILE_ID": "1",
        "PROFILE_NAME": "Personal",
    }
    assert (profiles_dir / "profile01.env").is_file()


def test_profile_commands_refuse_non_personal_profile(
    tmp_path, monkeypatch, capsys
):
    _, config, database_dir, profiles_dir = make_installed_profile(
        tmp_path, monkeypatch
    )
    old_db = store.DB_PATH
    store.DB_PATH = database_dir / "profiles.sqlite3"
    try:
        manager.save_env(
            profiles_dir / "profile01.env",
            {"PROFILE_ID": "1", "PROFILE_NAME": "Not Personal"},
        )
    finally:
        store.DB_PATH = old_db

    with patch("builtins.input", side_effect=AssertionError("Must not prompt")):
        personal_cli.command_profile_reset(Namespace())

    assert "not named Personal" in capsys.readouterr().out


def test_profile_command_without_installation_does_not_prompt(
    monkeypatch, capsys
):
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)

    with patch("builtins.input", side_effect=AssertionError("Must not prompt")):
        personal_cli.command_profile_reset(Namespace())

    assert "not initialized" in capsys.readouterr().out.lower()


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["profile", "show"], personal_cli.command_profile_show),
        (["profile", "edit"], personal_cli.command_profile_edit),
        (["profile", "reset"], personal_cli.command_profile_reset),
    ],
)
def test_profile_parser_routes_commands(arguments, expected):
    args = personal_cli.build_personal_parser().parse_args(arguments)
    assert args.func is expected
