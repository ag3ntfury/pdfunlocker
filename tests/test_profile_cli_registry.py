from __future__ import annotations

import argparse
from unittest.mock import patch

from pdfunlocker.cli import profile_cli
from pdfunlocker.profiles import manager


def test_archive_command_resolves_public_field_id_to_field_key():
    field = {"field_id": "6123", "field_key": "TRAVEL_TAG", "is_builtin": 0, "archived": 0}
    args = argparse.Namespace(field_id="6123")
    with patch.object(profile_cli, "_find_field", return_value=field) as find_field:
        with patch.object(manager, "archive_profile_field") as archive:
            profile_cli.command_field_archive(args)
    find_field.assert_called_once_with("6123")
    archive.assert_called_once_with("TRAVEL_TAG")


def test_archive_parser_uses_public_field_id_argument():
    args = profile_cli.build_parser().parse_args(["field", "archive", "6123"])
    assert args.field_id == "6123"
    assert not hasattr(args, "field_key")


def test_field_add_cli_returns_nonzero_when_field_creation_fails(capsys):
    with patch.object(manager, "add_profile_field", side_effect=ValueError("duplicate field key")):
        try:
            profile_cli.main(["field", "add"])
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("field add should exit nonzero when creation fails")

    assert "duplicate field key" in capsys.readouterr().err


def test_profile_storage_context_rejects_implicit_default_storage(monkeypatch):
    import pytest
    from pdfunlocker.cli import installer

    monkeypatch.setattr(installer, "find_installation_config", lambda: None)
    monkeypatch.delenv("PDFUNLOCKER_PROFILE_DEV_MODE", raising=False)

    with pytest.raises(RuntimeError, match="No completed Personal installation"):
        with profile_cli.profile_storage_context():
            pytest.fail("Must not silently use default profile storage")


def test_profile_storage_context_allows_explicit_development_mode(monkeypatch):
    from pdfunlocker.cli import installer

    monkeypatch.setattr(installer, "find_installation_config", lambda: None)
    monkeypatch.setenv("PDFUNLOCKER_PROFILE_DEV_MODE", "1")

    with profile_cli.profile_storage_context():
        pass
