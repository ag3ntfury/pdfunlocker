import json
from pathlib import Path

import pytest

from pdfunlocker.cli import installer
from pdfunlocker.profiles import store


@pytest.fixture(autouse=True)
def isolate_installation_locator(tmp_path, monkeypatch):
    """Prevent installer tests from touching the real installation locator."""
    locator = tmp_path / "installation.json"
    monkeypatch.setattr(installer, "INSTALLATION_LOCATOR", locator)
    monkeypatch.setattr(
        installer, "SETUP_RECOVERY_LOCATOR", tmp_path / "setup-recovery.json"
    )


def make_plan(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()

    return installer.build_plan(
        app_data=tmp_path / "app-data",
        source_directories=(source,),
        document_root=tmp_path / "documents",
    )


def test_ask_sources_supports_quoted_commas(tmp_path):
    source_one = tmp_path / "Family, Documents"
    source_two = tmp_path / "Archive"
    source_one.mkdir()
    source_two.mkdir()

    raw = f'"{source_one}",{source_two}'
    result = installer._ask_sources(input_func=lambda _: raw)

    assert result == (source_one.resolve(), source_two.resolve())


def test_interrupted_setup_rejects_different_paths(tmp_path):
    original_plan = make_plan(tmp_path)
    installer._write_setup_progress(original_plan, "directories_created")

    other_source = tmp_path / "other-source"
    other_source.mkdir()
    different_plan = installer.build_plan(
        app_data=tmp_path / "different-app-data",
        source_directories=(other_source,),
        document_root=tmp_path / "different-documents",
    )

    with pytest.raises(installer.SetupError, match="interrupted setup"):
        installer.apply_plan(different_plan)

    assert not different_plan.app_data.exists()
    assert not different_plan.document_root.exists()


def test_interrupted_setup_can_retry_with_same_paths(tmp_path):
    plan = make_plan(tmp_path)
    journal = installer._write_setup_progress(plan, "directories_created")

    result = installer.apply_plan(plan)

    assert result["profile_id"] > 0
    assert not journal.exists()
    assert not installer.SETUP_RECOVERY_LOCATOR.exists()
    assert installer.find_installation_config() == plan.config_file


def test_enterprise_selection_does_not_create_files(tmp_path, capsys):
    result = installer.run_setup(input_func=lambda _: "2")

    assert result is False
    assert "Enterprise will be available soon. Stay tuned!" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_invalid_edition_selection_does_not_create_files(tmp_path, capsys):
    result = installer.run_setup(input_func=lambda _: "invalid")

    assert result is False
    assert "Invalid edition selection" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_cancelled_setup_does_not_create_destinations(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    answers = iter([
        "1",
        str(tmp_path / "app-data"),
        str(source),
        str(tmp_path / "documents"),
        "n",
    ])

    result = installer.run_setup(input_func=lambda _: next(answers))

    assert result is False
    assert not (tmp_path / "app-data").exists()
    assert not (tmp_path / "documents").exists()


def test_validate_plan_rejects_missing_source(tmp_path):
    plan = installer.build_plan(
        app_data=tmp_path / "app-data",
        source_directories=(tmp_path / "missing",),
        document_root=tmp_path / "documents",
    )

    errors = installer.validate_plan(plan)

    assert any("does not exist" in error for error in errors)


def test_validate_plan_rejects_overlapping_source_and_document_root(tmp_path):
    source = tmp_path / "source"
    source.mkdir()

    plan = installer.build_plan(
        app_data=tmp_path / "app-data",
        source_directories=(source,),
        document_root=source / "documents",
    )

    errors = installer.validate_plan(plan)

    assert any("must not contain one another" in error for error in errors)


def test_personal_setup_creates_isolated_installation(tmp_path):
    plan = make_plan(tmp_path)
    original_db_path = store.DB_PATH

    result = installer.apply_plan(plan)

    assert store.DB_PATH == original_db_path
    assert result["profile_id"] > 0
    assert result["directories"] == 6
    assert result["rule_count"] > 0

    config = json.loads(plan.config_file.read_text(encoding="utf-8"))

    assert config["setup_complete"] is True
    assert config["edition"] == "personal"
    assert config["batch_size"] == 5
    assert config["profile_limit"] == 1

    for directory in plan.document_directories.values():
        assert directory.is_dir()

    profile_files = list(plan.profiles_directory.glob("*.env"))
    assert len(profile_files) == 1

    exported_profile = profile_files[0].read_text(encoding="utf-8")
    assert "PROFILE_NAME=Personal" in exported_profile

    database_path = plan.database_directory / "profiles.sqlite3"
    assert database_path.is_file()
    assert not list(plan.document_root.rglob("*.pdf"))


def test_personal_setup_is_idempotent(tmp_path):
    plan = make_plan(tmp_path)
    original_db_path = store.DB_PATH

    first = installer.apply_plan(plan)
    second = installer.apply_plan(plan)

    assert first["profile_id"] == second["profile_id"]
    assert store.DB_PATH == original_db_path

    profile_files = list(plan.profiles_directory.glob("*.env"))
    assert len(profile_files) == 1

    config = json.loads(plan.config_file.read_text(encoding="utf-8"))
    assert config["profile_id"] == first["profile_id"]


def test_profile_database_path_is_restored_after_failure(tmp_path, monkeypatch):
    plan = make_plan(tmp_path)
    original_db_path = store.DB_PATH

    def fail_initialize():
        raise RuntimeError("simulated database initialization failure")

    monkeypatch.setattr(store, "initialize", fail_initialize)

    with pytest.raises(RuntimeError, match="simulated database initialization failure"):
        installer._initialize_personal_profile(plan)

    assert store.DB_PATH == original_db_path


def test_custom_app_data_installation_is_discoverable(tmp_path):
    plan = make_plan(tmp_path)

    installer.apply_plan(plan)

    assert installer.find_installation_config() == plan.config_file


def test_locator_rejects_incomplete_or_invalid_config(tmp_path):
    locator = installer.INSTALLATION_LOCATOR
    config_path = tmp_path / "config.json"

    config_path.write_text(
        json.dumps({"setup_complete": False, "edition": "personal"}),
        encoding="utf-8",
    )
    locator.write_text(
        json.dumps({"config_file": str(config_path)}),
        encoding="utf-8",
    )

    assert installer.find_installation_config() is None


def test_locator_rejects_malformed_json(tmp_path):
    locator = installer.INSTALLATION_LOCATOR
    locator.write_text("{invalid json", encoding="utf-8")

    assert installer.find_installation_config() is None
