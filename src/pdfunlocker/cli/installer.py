"""First-run edition selector and safe Personal edition installer.

This installer creates a new, isolated installation. It never inspects,
migrates, or modifies legacy installations and never scans PDF files.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


DOCUMENT_FOLDERS = (
    "Inbox",
    "Original",
    "Unlocked",
    "Locked",
    "Corrupted",
    "Unsupported",
)

DEFAULT_APP_DATA = Path.home() / ".local" / "share" / "pdfunlocker"

INSTALLATION_LOCATOR = DEFAULT_APP_DATA / "installation.json"
SETUP_RECOVERY_LOCATOR = DEFAULT_APP_DATA / "setup-recovery.json"
DEFAULT_DOCUMENT_ROOT = (
    Path.home() / "storage" / "shared" / "PDF Documents"
    if (Path.home() / "storage" / "shared").is_dir()
    else Path.home() / "PDF Documents"
)


class SetupCancelled(Exception):
    """Raised when setup is cancelled before changes begin."""


class SetupError(Exception):
    """Raised when setup cannot safely continue."""


@dataclass(frozen=True)
class SetupPlan:
    edition: str
    app_data: Path
    config_file: Path
    source_directories: tuple[Path, ...]
    document_root: Path
    document_directories: dict[str, Path]
    database_directory: Path
    profiles_directory: Path
    rules_directory: Path
    logs_directory: Path


def _resolved(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_plan(plan: SetupPlan) -> list[str]:
    """Validate all paths without creating or modifying anything."""
    errors: list[str] = []

    if plan.edition != "personal":
        errors.append("Only the Personal edition can currently be installed.")

    if not plan.source_directories:
        errors.append("At least one source directory is required.")

    sources = list(plan.source_directories)

    if len(set(sources)) != len(sources):
        errors.append("Duplicate source directories were supplied.")

    for source in sources:
        if not source.exists():
            errors.append(f"Source directory does not exist: {source}")
        elif not source.is_dir():
            errors.append(f"Source path is not a directory: {source}")
        elif not os.access(source, os.R_OK | os.X_OK):
            errors.append(f"Source directory is not readable: {source}")

    for index, source in enumerate(sources):
        for other in sources[index + 1:]:
            if _is_within(source, other) or _is_within(other, source):
                errors.append(
                    f"Source directories must not contain one another: "
                    f"{source} and {other}"
                )

    for source in sources:
        if (
            _is_within(source, plan.document_root)
            or _is_within(plan.document_root, source)
        ):
            errors.append(
                "Document root and source directories must not contain "
                f"one another: {source}"
            )

        if (
            _is_within(source, plan.app_data)
            or _is_within(plan.app_data, source)
        ):
            errors.append(
                f"App-data directory and source directory must not overlap: "
                f"{source}"
            )

    if (
        _is_within(plan.app_data, plan.document_root)
        or _is_within(plan.document_root, plan.app_data)
    ):
        errors.append(
            "App-data and document-root directories must not overlap."
        )

    if set(plan.document_directories) != set(DOCUMENT_FOLDERS):
        errors.append(
            "Document folder plan is incomplete or contains unexpected folders."
        )

    for name in DOCUMENT_FOLDERS:
        expected = plan.document_root / name
        if plan.document_directories.get(name) != expected:
            errors.append(f"Invalid planned path for document folder: {name}")

    destinations = [
        plan.app_data,
        plan.config_file.parent,
        plan.database_directory,
        plan.profiles_directory,
        plan.rules_directory,
        plan.logs_directory,
        plan.document_root,
        *plan.document_directories.values(),
    ]

    for destination in destinations:
        if destination.exists():
            if not destination.is_dir():
                errors.append(
                    f"Destination exists but is not a directory: {destination}"
                )
            elif not os.access(destination, os.W_OK | os.X_OK):
                errors.append(
                    f"Destination directory is not writable: {destination}"
                )
            continue

        probe = destination
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent

        if probe.exists() and not os.access(probe, os.W_OK | os.X_OK):
            errors.append(f"Destination parent is not writable: {probe}")

    return errors


def build_plan(
    app_data: Path,
    source_directories: tuple[Path, ...],
    document_root: Path,
) -> SetupPlan:
    app_data = _resolved(app_data)
    document_root = _resolved(document_root)
    sources = tuple(_resolved(path) for path in source_directories)

    return SetupPlan(
        edition="personal",
        app_data=app_data,
        config_file=app_data / "config" / "config.json",
        source_directories=sources,
        document_root=document_root,
        document_directories={
            name: document_root / name for name in DOCUMENT_FOLDERS
        },
        database_directory=app_data / "database",
        profiles_directory=app_data / "profiles",
        rules_directory=app_data / "rules",
        logs_directory=app_data / "logs",
    )


def _ask_path(
    prompt: str,
    default: Path | None = None,
    input_func: Callable[[str], str] = input,
) -> Path:
    while True:
        suffix = f" [{default}]" if default is not None else ""
        value = input_func(f"{prompt}{suffix}: ").strip()

        if not value and default is not None:
            return _resolved(default)

        if value:
            return _resolved(value)

        print("Please enter a path.")


def _ask_sources(
    input_func: Callable[[str], str] = input,
) -> tuple[Path, ...]:
    print()
    print("Enter source directories containing PDFs.")
    print("Separate multiple paths with commas.")
    print('If a path contains a comma, enclose that path in double quotes.')

    while True:
        raw = input_func("Source directories: ").strip()

        if not raw:
            print("At least one source directory is required.")
            continue

        try:
            values = next(csv.reader([raw], skipinitialspace=True, strict=True))
        except csv.Error as exc:
            print(f"Could not parse source directories: {exc}")
            print('Use commas between paths and double quotes around paths containing commas.')
            continue

        values = [value.strip() for value in values if value.strip()]
        if not values:
            print("At least one source directory is required.")
            continue

        return tuple(_resolved(value) for value in values)


def _show_plan(plan: SetupPlan) -> None:
    print()
    print("Personal edition setup summary")
    print("==============================")
    print(f"App data       : {plan.app_data}")
    print(f"Configuration  : {plan.config_file}")
    print(f"Database       : {plan.database_directory}")
    print(f"Profiles       : {plan.profiles_directory}")
    print(f"Rules          : {plan.rules_directory}")
    print(f"Logs           : {plan.logs_directory}")
    print()
    print("Source directories:")
    for source in plan.source_directories:
        print(f"  - {source}")

    print()
    print(f"Document root  : {plan.document_root}")
    for name in DOCUMENT_FOLDERS:
        print(f"  {name:<12}: {plan.document_directories[name]}")

    print()
    print("No source PDFs will be scanned or copied during setup.")


def _atomic_json_write(path: Path, data: dict) -> None:
    """Write JSON atomically with private file permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, path)

        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass

    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise



def find_installation_config() -> Path | None:
    """Find the active installation without inspecting legacy locations."""
    locator = INSTALLATION_LOCATOR

    try:
        data = json.loads(locator.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    value = data.get("config_file")
    if not isinstance(value, str) or not value.strip():
        return None

    config_path = _resolved(value)

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None

    if not isinstance(config, dict) or config.get("setup_complete") is not True:
        return None

    if config.get("edition") != "personal":
        return None

    return config_path


def _write_installation_locator(config_file: Path) -> None:
    """Atomically register the active configuration for future CLI launches."""
    _atomic_json_write(
        INSTALLATION_LOCATOR,
        {
            "version": 1,
            "edition": "personal",
            "config_file": str(config_file),
        },
    )


def _copy_prefilled_rules(destination: Path) -> int:
    """Copy bundled rules without overwriting different existing files."""
    source_directory = Path(__file__).resolve().parents[3] / "rules"

    if not source_directory.is_dir():
        raise SetupError(
            f"Bundled rules directory was not found: {source_directory}"
        )

    rule_files = sorted(source_directory.glob("rule*.yml"))

    if not rule_files:
        raise SetupError(
            f"No bundled rule files were found in: {source_directory}"
        )

    destination.mkdir(parents=True, exist_ok=True)
    copied = 0

    for source_file in rule_files:
        target = destination / source_file.name

        if target.exists():
            if not target.is_file():
                raise SetupError(f"Rule destination is not a file: {target}")

            if target.read_bytes() != source_file.read_bytes():
                raise SetupError(
                    f"Rule destination already contains a different file: "
                    f"{target}"
                )
            continue

        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=destination,
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            shutil.copy2(source_file, temporary)

            if temporary.read_bytes() != source_file.read_bytes():
                raise SetupError(
                    f"Rule copy verification failed for: {source_file}"
                )

            os.replace(temporary, target)
            copied += 1
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    return copied


def _initialize_personal_profile(plan: SetupPlan) -> int:
    """Initialize the isolated profile DB and generate its .env export."""
    from pdfunlocker.profiles import manager as profile_manager
    from pdfunlocker.profiles import store

    previous_db_path = store.DB_PATH
    store.DB_PATH = plan.database_directory / "profiles.sqlite3"

    try:
        store.initialize()

        profiles = store.list_profiles()
        existing = next(
            (
                item
                for item in profiles
                if str(item.get("name", "")).strip().casefold() == "personal"
            ),
            None,
        )

        if existing:
            profile_id = int(existing["profile_id"])
            stored_values = store.load_profile(profile_id)

            if stored_values is None:
                raise SetupError(
                    "Personal profile exists but its SQLite values are missing."
                )

            profile_path = plan.profiles_directory / (
                f"profile{profile_id:02d}.env"
            )
            profile_manager.save_env(profile_path, stored_values)
            return profile_id

        profile_id = store.reserve_profile_id()
        profile_path = plan.profiles_directory / (
            f"profile{profile_id:02d}.env"
        )

        profile_manager.save_env(
            profile_path,
            {
                "PROFILE_ID": str(profile_id),
                "PROFILE_NAME": "Personal",
            },
        )
        return profile_id

    finally:
        store.DB_PATH = previous_db_path


def _setup_journal_path(plan: SetupPlan) -> Path:
    return plan.app_data / "setup-progress.json"


def _write_setup_progress(plan: SetupPlan, stage: str) -> Path:
    """Persist a non-sensitive checkpoint so an interrupted setup is diagnosable.

    Re-running setup with the same paths is safe: directory creation, rule
    copying, and Personal profile initialization are designed to be idempotent.
    """
    journal = _setup_journal_path(plan)
    _atomic_json_write(
        journal,
        {
            "version": 1,
            "status": "in_progress",
            "stage": stage,
            "config_file": str(plan.config_file),
            "app_data_directory": str(plan.app_data),
            "source_directories": [str(path) for path in plan.source_directories],
            "document_root": str(plan.document_root),
            "database_directory": str(plan.database_directory),
            "profiles_directory": str(plan.profiles_directory),
            "rules_directory": str(plan.rules_directory),
            "logs_directory": str(plan.logs_directory),
            "document_directories": {
                name: str(path) for name, path in plan.document_directories.items()
            },
        },
    )
    # This pointer makes a failed setup discoverable even when app data is
    # outside the default location. It is not an active-installation locator.
    _atomic_json_write(
        SETUP_RECOVERY_LOCATOR,
        {"version": 1, "journal_file": str(journal)},
    )
    return journal


def find_incomplete_setup() -> dict | None:
    """Return a valid interrupted-setup journal, without touching its files."""
    try:
        pointer = json.loads(SETUP_RECOVERY_LOCATOR.read_text(encoding="utf-8"))
        journal_value = pointer.get("journal_file") if isinstance(pointer, dict) else None
        if not isinstance(journal_value, str) or not journal_value.strip():
            return None
        journal_path = _resolved(journal_value)
        data = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, AttributeError):
        return None

    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or data.get("status") != "in_progress"
    ):
        return None
    data["journal_file"] = str(journal_path)
    return data



def _recovery_matches_plan(plan: SetupPlan, recovery: dict) -> bool:
    """Return whether a retry uses exactly the paths recorded by the journal."""
    expected = {
        "config_file": str(plan.config_file),
        "app_data_directory": str(plan.app_data),
        "source_directories": [str(path) for path in plan.source_directories],
        "document_root": str(plan.document_root),
        "database_directory": str(plan.database_directory),
        "profiles_directory": str(plan.profiles_directory),
        "rules_directory": str(plan.rules_directory),
        "logs_directory": str(plan.logs_directory),
        "document_directories": {
            name: str(path) for name, path in plan.document_directories.items()
        },
    }
    return all(recovery.get(key) == value for key, value in expected.items())


def _explain_recovery_path_mismatch(recovery: dict) -> str:
    return (
        "An interrupted setup already exists with different paths. "
        "To avoid abandoning or mixing partial installation data, retry "
        "using the original app-data, source, and document-root paths. "
        f"Recovery journal: {recovery.get('journal_file', 'unknown')}"
    )

def apply_plan(plan: SetupPlan) -> dict:
    """Apply a validated and confirmed setup plan.

    Operations are idempotent where possible. The completion config is written
    last, so an interrupted setup is not reported as complete.
    """
    active_config = find_installation_config()
    if active_config is not None:
        if active_config.resolve() != plan.config_file.resolve():
            raise SetupError(
                "A Personal edition installation is already active at "
                f"{active_config}. Setup cannot replace it. "
                "Use the existing installation or back it up before "
                "planning a separate installation."
            )

    recovery = find_incomplete_setup()
    if recovery is not None and not _recovery_matches_plan(plan, recovery):
        raise SetupError(_explain_recovery_path_mismatch(recovery))

    errors = validate_plan(plan)
    if errors:
        raise SetupError("\n".join(errors))

    journal = _write_setup_progress(plan, "starting")

    directories = (
        plan.app_data,
        plan.config_file.parent,
        plan.database_directory,
        plan.profiles_directory,
        plan.rules_directory,
        plan.logs_directory,
        plan.document_root,
        *plan.document_directories.values(),
    )

    try:
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
        _write_setup_progress(plan, "directories_created")

        copied_rules = _copy_prefilled_rules(plan.rules_directory)
        _write_setup_progress(plan, "rules_copied")

        from pdfunlocker.rules import manager as rules_manager

        previous_rules_dir = rules_manager.RULES_DIR
        rules_manager.RULES_DIR = plan.rules_directory

        try:
            rules = rules_manager.load_rules()
        finally:
            rules_manager.RULES_DIR = previous_rules_dir

        if not rules:
            raise SetupError(
                "No valid rules were loaded; setup was not finalized."
            )
        _write_setup_progress(plan, "rules_validated")

        profile_id = _initialize_personal_profile(plan)
        _write_setup_progress(plan, "profile_initialized")

        config = {
            "version": "0.1.0",
            "edition": "personal",
            "setup_complete": True,
            "app_directory": str(plan.app_data),
            "app_data_directory": str(plan.app_data),
            "config_file": str(plan.config_file),
            "source_directories": [
                str(path) for path in plan.source_directories
            ],
            "document_root": str(plan.document_root),
            "inbox_directory": str(plan.document_directories["Inbox"]),
            "original_directory": str(plan.document_directories["Original"]),
            "unlocked_directory": str(plan.document_directories["Unlocked"]),
            "locked_directory": str(plan.document_directories["Locked"]),
            "corrupted_directory": str(plan.document_directories["Corrupted"]),
            "unsupported_directory": str(
                plan.document_directories["Unsupported"]
            ),
            "database_directory": str(plan.database_directory),
            "profiles_directory": str(plan.profiles_directory),
            "rules_directory": str(plan.rules_directory),
            "logs_directory": str(plan.logs_directory),
            "profile_id": profile_id,
            "profile_limit": 1,
            "batch_size": 5,
        }

        _atomic_json_write(plan.config_file, config)
        _write_setup_progress(plan, "configuration_written")
        _write_installation_locator(plan.config_file)
        _write_setup_progress(plan, "installation_registered")

        journal.unlink(missing_ok=True)
        SETUP_RECOVERY_LOCATOR.unlink(missing_ok=True)

        return {
            "config": plan.config_file,
            "profile_id": profile_id,
            "rule_count": len(rules),
            "rules_copied": copied_rules,
            "directories": len(DOCUMENT_FOLDERS),
        }
    except Exception as exc:
        # Keep the last successful checkpoint and all non-destructive artifacts.
        if isinstance(exc, SetupError):
            raise
        raise SetupError(
            f"Setup stopped during stage '{_read_setup_stage(plan)}': {exc}. "
            f"Recovery journal: {journal}"
        ) from exc


def _read_setup_stage(plan: SetupPlan) -> str:
    try:
        data = json.loads(_setup_journal_path(plan).read_text(encoding="utf-8"))
        stage = data.get("stage") if isinstance(data, dict) else None
        return str(stage or "unknown")
    except (OSError, json.JSONDecodeError, TypeError):
        return "unknown"


def run_setup(
    input_func: Callable[[str], str] = input,
) -> bool:
    """Run edition selection and the Personal setup wizard."""
    active_config = find_installation_config()
    if active_config is not None:
        print("PDF Unlocker is already initialized.")
        print(f"Active configuration: {active_config}")
        print("Setup was not restarted and no files were changed.")
        return False

    recovery = find_incomplete_setup()
    if recovery:
        print()
        print("An earlier setup was interrupted.")
        print(f"Last completed stage: {recovery.get('stage', 'unknown')}")
        print(f"Recovery journal: {recovery['journal_file']}")
        print("You can safely retry with the same paths; completed setup")
        print("artifacts will be reused and no PDFs will be scanned.")

    print()
    print("========================================")
    print("             PDF Unlocker")
    print("========================================")
    print()
    print("Select edition:")
    print("  1. Personal")
    print("  2. Enterprise")

    try:
        choice = input_func("Edition [1/2]: ").strip()

        if choice == "2":
            print("Enterprise will be available soon. Stay tuned!")
            return False

        if choice != "1":
            print("Invalid edition selection. No changes were made.")
            return False

        print()
        print("Personal edition setup")
        print("----------------------")

        app_data = _ask_path(
            "App-data directory",
            DEFAULT_APP_DATA,
            input_func,
        )
        sources = _ask_sources(input_func)
        document_root = _ask_path(
            "Document root",
            DEFAULT_DOCUMENT_ROOT,
            input_func,
        )

        plan = build_plan(app_data, sources, document_root)
        if recovery is not None and not _recovery_matches_plan(plan, recovery):
            print()
            print("Setup recovery path mismatch:")
            print(_explain_recovery_path_mismatch(recovery))
            print("No files were changed.")
            return False

        errors = validate_plan(plan)

        if errors:
            print()
            print("Setup validation failed:")
            for error in errors:
                print(f"  - {error}")
            return False

        _show_plan(plan)

        answer = input_func(
            "\nCreate these directories and initialize Personal edition? "
            "[y/N]: "
        ).strip().casefold()

        if answer not in {"y", "yes"}:
            print("Setup cancelled. No setup changes were made.")
            return False

        result = apply_plan(plan)

    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled. No further changes were requested.")
        return False
    except Exception as exc:
        print(f"Setup failed: {type(exc).__name__}: {exc}")
        recovery = find_incomplete_setup()
        if recovery:
            print()
            print("An incomplete setup checkpoint was saved.")
            print(f"Last recorded stage: {recovery.get('stage', 'unknown')}")
            print(f"Recovery journal: {recovery['journal_file']}")
            print("Retry setup using the same app-data, source, and document paths.")
            print("Existing setup files will be reused; no PDFs will be scanned.")
        else:
            print("Review the paths and permissions before retrying.")
        print("No PDFs were scanned.")
        return False

    print()
    print("========================================")
    print("             Setup Complete")
    print("========================================")
    print(f"Configuration : {result['config']}")
    print(f"Personal ID   : {result['profile_id']}")
    print(f"Valid rules   : {result['rule_count']}")
    print(f"Rules copied  : {result['rules_copied']}")
    print(f"Document dirs : {result['directories']}")
    print()
    print("No PDF files were scanned, moved, or unlocked.")
    return True
