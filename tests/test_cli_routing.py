from pathlib import Path

from pdfunlocker.cli import installer, main, personal_cli


def test_install_routes_to_new_setup_wizard(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)
    monkeypatch.setattr(personal_cli, "main", lambda args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["pdfunlocker", "install"])

    main.main()

    assert calls == [["setup"]]


def test_install_preserves_extra_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)
    monkeypatch.setattr(personal_cli, "main", lambda args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["pdfunlocker", "install", "--help"])

    main.main()

    assert calls == [["setup", "--help"]]


def test_installed_direct_rule_help_uses_personal_rules(monkeypatch):
    calls = []
    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: Path("/temporary/personal/config.json"),
    )
    monkeypatch.setattr(
        personal_cli,
        "show_rule_reference",
        lambda reference: calls.append(reference),
    )
    monkeypatch.setattr("sys.argv", ["pdfunlocker", "rule12", "--help"])

    main.main()

    assert calls == ["00012"]


def test_installed_personal_commands_use_personal_cli(monkeypatch):
    calls = []
    monkeypatch.setattr(
        installer,
        "find_installation_config",
        lambda: Path("/temporary/personal/config.json"),
    )
    monkeypatch.setattr(personal_cli, "main", lambda args: calls.append(args))
    monkeypatch.setattr("sys.argv", ["pdfunlocker", "rules", "list"])

    main.main()

    assert calls == [["rules", "list"]]


def test_uninstalled_direct_rule_help_uses_repository_rules(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "find_installation_config", lambda: None)

    from pdfunlocker.rules import manager
    monkeypatch.setattr(manager, "show_rule", lambda reference: calls.append(reference))
    monkeypatch.setattr("sys.argv", ["pdfunlocker", "rule7", "--help"])

    main.main()

    assert calls == ["00007"]
