import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import yaml

from pdfunlocker.cli import installer, personal_cli
from pdfunlocker.rules import manager


def make_installation(tmp_path, monkeypatch):
    app_data = tmp_path / "personal-app"
    rules_dir = app_data / "rules"
    rules_dir.mkdir(parents=True)
    config_path = app_data / "config.json"
    config = {
        "setup_complete": True,
        "edition": "personal",
        "app_data_directory": str(app_data),
        "rules_directory": str(rules_dir),
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(
        installer, "find_installation_config", lambda: config_path
    )
    return rules_dir


def write_rule(directory, number, rule_id, priority="Z", name="Test rule"):
    path = directory / f"rule{number}.yml"
    data = {
        "rule": {
            "number": number,
            "id": rule_id,
            "name": name,
            "category": "test",
            "priority": priority,
        },
        "pattern": {
            "fields": [
                {"field_id": "001", "slice": {"mode": "full"}}
            ]
        },
        "transform": {"case": "raw"},
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_rules_context_uses_personal_directory_and_restores_global(
    tmp_path, monkeypatch
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    previous = manager.RULES_DIR

    with personal_cli._personal_rules_context(
        {"rules_directory": str(rules_dir)}
    ) as active_manager:
        assert active_manager is manager
        assert manager.RULES_DIR == rules_dir

    assert manager.RULES_DIR == previous


def test_rules_context_refuses_missing_personal_directory(tmp_path):
    missing = tmp_path / "missing-rules"
    previous = manager.RULES_DIR

    try:
        with personal_cli._personal_rules_context(
            {"rules_directory": str(missing)}
        ):
            raise AssertionError("Context should not be entered")
    except RuntimeError as exc:
        assert "does not exist" in str(exc)

    assert manager.RULES_DIR == previous


def test_rules_list_uses_personal_rules_only(
    tmp_path, monkeypatch, capsys
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    write_rule(rules_dir, "00001", "personal-one", "A1", "Personal rule")
    previous = manager.RULES_DIR

    personal_cli.command_rules_list(Namespace())

    output = capsys.readouterr().out
    assert "Personal rule" in output
    assert manager.RULES_DIR == previous


def test_rules_show_accepts_rule_reference(
    tmp_path, monkeypatch, capsys
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    write_rule(rules_dir, "00001", "personal-one", name="Shown rule")

    personal_cli.command_rules_show(Namespace(rule_id="personal-one"))

    output = capsys.readouterr().out
    assert "Shown rule" in output
    assert "00001" in output


def test_rules_validate_passes_for_valid_rules(
    tmp_path, monkeypatch, capsys
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    write_rule(rules_dir, "00001", "one", "A1")
    second_rule = write_rule(rules_dir, "00002", "two", "Z")
    second_data = yaml.safe_load(second_rule.read_text(encoding="utf-8"))
    second_data["pattern"]["fields"][0]["field_id"] = "002"
    second_rule.write_text(
        yaml.safe_dump(second_data, sort_keys=False),
        encoding="utf-8",
    )

    before = {
        path.name: path.read_bytes()
        for path in rules_dir.glob("*.yml")
    }

    personal_cli.command_rules_validate(Namespace())

    output = capsys.readouterr().out
    assert "All active Personal rules are valid." in output
    assert "No rule files were changed." in output
    assert before == {
        path.name: path.read_bytes()
        for path in rules_dir.glob("*.yml")
    }


def test_rules_validate_reports_invalid_yaml(
    tmp_path, monkeypatch, capsys
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    (rules_dir / "rule00001.yml").write_text(
        "rule: [invalid", encoding="utf-8"
    )

    personal_cli.command_rules_validate(Namespace())

    output = capsys.readouterr().out
    assert "Validation failed" in output
    assert "rule00001.yml" in output


def test_rules_validate_reports_duplicate_executable_priority(
    tmp_path, monkeypatch, capsys
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    write_rule(rules_dir, "00001", "one", "A1")
    write_rule(rules_dir, "00002", "two", "A1")

    personal_cli.command_rules_validate(Namespace())

    output = capsys.readouterr().out
    assert "duplicate executable priority A1" in output


def test_rules_validate_reports_duplicate_candidate_pattern(
    tmp_path, monkeypatch, capsys
):
    rules_dir = make_installation(tmp_path, monkeypatch)
    write_rule(rules_dir, "00001", "one", "A1")
    write_rule(rules_dir, "00002", "two", "Z")

    personal_cli.command_rules_validate(Namespace())

    output = capsys.readouterr().out
    assert "duplicate candidate-generation pattern" in output


def test_rules_parser_routes_all_read_only_commands():
    parser = personal_cli.build_personal_parser()

    assert parser.parse_args(["rules", "list"]).func is personal_cli.command_rules_list
    assert parser.parse_args(["rules", "validate"]).func is personal_cli.command_rules_validate
    shown = parser.parse_args(["rules", "show", "00001"])
    assert shown.func is personal_cli.command_rules_show
    assert shown.rule_id == "00001"


def test_personal_parser_still_rejects_rule_mutations():
    parser = personal_cli.build_personal_parser()

    for arguments in (
        ["rules", "add"],
        ["rules", "modify", "00001"],
        ["rules", "remove", "00001"],
    ):
        try:
            parser.parse_args(arguments)
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"Unexpectedly accepted: {arguments}")
