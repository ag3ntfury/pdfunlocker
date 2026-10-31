import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.cli import installer, personal_cli


def make_config(tmp_path):
    app_data = tmp_path / "app-data"
    document_root = tmp_path / "documents"
    source = tmp_path / "source"
    source.mkdir()
    app_data.mkdir()
    document_root.mkdir()

    config_path = app_data / "config" / "config.json"
    config = {
        "setup_complete": True,
        "edition": "personal",
        "app_data_directory": str(app_data),
        "document_root": str(document_root),
        "database_directory": str(app_data / "database"),
        "profiles_directory": str(app_data / "profiles"),
        "rules_directory": str(app_data / "rules"),
        "logs_directory": str(app_data / "logs"),
        "source_directories": [str(source)],
        "profile_id": "personal",
    }
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, config, source


def test_config_edit_updates_only_source_directories(tmp_path, monkeypatch):
    config_path, original, old_source = make_config(tmp_path)
    new_source = tmp_path / "new-source"
    new_source.mkdir()

    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: config_path,
    )
    monkeypatch.setattr(
        installer,
        "_ask_sources",
        lambda input_func: (new_source,),
    )

    with patch("builtins.input", return_value="yes"):
        personal_cli.command_config_edit(Namespace())

    updated = json.loads(config_path.read_text(encoding="utf-8"))

    assert updated["source_directories"] == [str(new_source.resolve())]
    for key, value in original.items():
        if key != "source_directories":
            assert updated[key] == value
    assert old_source.is_dir()
    assert new_source.is_dir()


def test_config_edit_cancel_does_not_write(tmp_path, monkeypatch):
    config_path, original, _ = make_config(tmp_path)
    new_source = tmp_path / "new-source"
    new_source.mkdir()

    before = config_path.read_bytes()

    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: config_path,
    )
    monkeypatch.setattr(
        installer,
        "_ask_sources",
        lambda input_func: (new_source,),
    )

    with patch("builtins.input", return_value="no"):
        personal_cli.command_config_edit(Namespace())

    assert config_path.read_bytes() == before


def test_config_edit_rejects_invalid_source_without_writing(
    tmp_path,
    monkeypatch,
):
    config_path, _, _ = make_config(tmp_path)
    missing_source = tmp_path / "does-not-exist"
    before = config_path.read_bytes()

    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: config_path,
    )
    monkeypatch.setattr(
        installer,
        "_ask_sources",
        lambda input_func: (missing_source,),
    )

    personal_cli.command_config_edit(Namespace())

    assert config_path.read_bytes() == before


def test_config_edit_without_installation_does_not_prompt(monkeypatch, capsys):
    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: None,
    )

    with patch(
        "builtins.input",
        side_effect=AssertionError("Must not prompt without installation"),
    ):
        personal_cli.command_config_edit(Namespace())

    assert "not initialized" in capsys.readouterr().out


def test_config_edit_parser_is_registered():
    parser = personal_cli.build_personal_parser()
    args = parser.parse_args(["config", "edit"])

    assert args.func is personal_cli.command_config_edit
