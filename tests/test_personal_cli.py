from pathlib import Path
from unittest.mock import patch

import pytest

from pdfunlocker.cli import installer, main as cli
from pdfunlocker.cli import personal_cli


def test_help_does_not_start_setup(monkeypatch, capsys):
    monkeypatch.setattr(
        installer, "run_setup",
        lambda: pytest.fail("Help must not start setup"),
    )

    with patch("sys.argv", ["pdfunlocker", "--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()

    assert exc.value.code == 0
    assert "PDF Unlocker Personal Edition" in capsys.readouterr().out


def test_version_does_not_start_setup(monkeypatch, capsys):
    monkeypatch.setattr(
        installer, "run_setup",
        lambda: pytest.fail("Version must not start setup"),
    )

    with patch("sys.argv", ["pdfunlocker", "--version"]):
        with pytest.raises(SystemExit) as exc:
            cli.main()

    assert exc.value.code == 0
    assert "pdfunlocker" in capsys.readouterr().out


def test_status_without_installation(monkeypatch, capsys):
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)

    with patch("sys.argv", ["pdfunlocker", "status"]):
        cli.main()

    output = capsys.readouterr().out
    assert "not initialized" in output
    assert "pdfunlocker setup" in output


def test_no_arguments_starts_setup_when_not_installed(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)
    monkeypatch.setattr(installer, "run_setup", lambda: calls.append("setup"))

    with patch("sys.argv", ["pdfunlocker"]):
        cli.main()

    assert calls == ["setup"]


def test_no_arguments_shows_menu_when_installed(monkeypatch, capsys):
    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: Path("/temporary/config.json"),
    )
    monkeypatch.setattr(
        installer,
        "run_setup",
        lambda: pytest.fail("Installed CLI must not restart setup"),
    )

    with patch("sys.argv", ["pdfunlocker"]):
        cli.main()

    assert "PDF Unlocker — Personal Edition" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["rules", "add"],
        ["rules", "modify", "00001"],
        ["rules", "remove", "00001"],
        ["profile", "add"],
        ["profile", "delete"],
        ["install"],
    ],
)
def test_installed_personal_cli_rejects_legacy_mutations(
    monkeypatch, arguments
):
    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: Path("/temporary/config.json"),
    )

    with patch("sys.argv", ["pdfunlocker", *arguments]):
        with pytest.raises(SystemExit) as exc:
            cli.main()

    assert exc.value.code == 2


def test_setup_command_runs_setup_wizard(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)
    monkeypatch.setattr(installer, "run_setup", lambda: calls.append("setup"))

    with patch("sys.argv", ["pdfunlocker", "setup"]):
        cli.main()

    assert calls == ["setup"]


def test_personal_parser_does_not_expose_rule_mutation_commands():
    parser = personal_cli.build_personal_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["rules", "add"])

    with pytest.raises(SystemExit):
        parser.parse_args(["rules", "remove", "00001"])
