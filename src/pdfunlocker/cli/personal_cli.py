from __future__ import annotations

import argparse
import json
import sys
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Iterator, Sequence

from pdfunlocker.cli import installer


def _version() -> str:
    try:
        return version("pdfunlocker")
    except PackageNotFoundError:
        return "0.1.0"


def _print_menu() -> None:
    print("PDF Unlocker — Personal Edition")
    print()
    print("Available commands:")
    print("  pdfunlocker status")
    print("  pdfunlocker config show")
    print("  pdfunlocker config edit")
    print("  pdfunlocker profile show")
    print("  pdfunlocker profile edit")
    print("  pdfunlocker profile reset")
    print("  pdfunlocker rules list")
    print("  pdfunlocker rules show RULE_ID")
    print("  pdfunlocker rules validate")
    print("  pdfunlocker scan")
    print("  pdfunlocker unlock")
    print("  pdfunlocker retry")
    print("  pdfunlocker check-corrupted")
    print()
    print("Run 'pdfunlocker --help' for command help.")


def _load_config(config_path: Path) -> dict:
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot read installation configuration: {exc}"
        ) from exc

    if not isinstance(data, dict) or data.get("setup_complete") is not True:
        raise RuntimeError("The installation configuration is incomplete.")

    return data


def _active_config() -> tuple[Path, dict] | None:
    config_path = installer.find_installation_config()
    if config_path is None:
        return None
    return config_path, _load_config(config_path)


def _require_active_config() -> tuple[Path, dict] | None:
    try:
        active = _active_config()
    except RuntimeError as exc:
        print(exc)
        return None

    if active is None:
        print("PDF Unlocker is not initialized. Run: pdfunlocker setup")
    return active


def command_status(_: argparse.Namespace) -> None:
    active = _require_active_config()
    if active is None:
        return

    config_path, config = active
    print("PDF Unlocker — Personal Edition")
    print("Installation: initialized")
    print(f"Configuration: {config_path}")
    print(f"Application data: {config.get('app_data_directory', 'Not configured')}")
    print(f"Document root: {config.get('document_root', 'Not configured')}")

    database_directory = config.get("database_directory")
    database_path = (
        Path(database_directory) / "profiles.sqlite3"
        if isinstance(database_directory, str) and database_directory
        else None
    )
    print(f"Database: {database_path or 'Not configured'}")
    print(f"Profile ID: {config.get('profile_id', 'Not configured')}")
    print(f"Source folders: {len(config.get('source_directories', []))}")


def command_config_show(_: argparse.Namespace) -> None:
    active = _require_active_config()
    if active is None:
        return

    _, config = active
    print(json.dumps(config, indent=2, ensure_ascii=False))


def command_config_edit(_: argparse.Namespace) -> None:
    active = _require_active_config()
    if active is None:
        return

    config_path, config = active

    required_paths = ("app_data_directory", "document_root")
    missing = [
        key for key in required_paths
        if not isinstance(config.get(key), str) or not config[key].strip()
    ]
    if missing:
        print(
            "Cannot edit source folders because required configuration "
            f"paths are missing: {', '.join(missing)}"
        )
        return

    print("Edit source folders")
    print("===================")
    print("Only source folders can be changed here.")
    print("Application data, database, profiles, rules, logs and document")
    print("storage locations will remain unchanged.")
    print()
    print("Current source folders:")
    for source in config.get("source_directories", []):
        print(f"  - {source}")

    try:
        new_sources = installer._ask_sources(input_func=input)
        plan = installer.build_plan(
            app_data=Path(config["app_data_directory"]),
            source_directories=new_sources,
            document_root=Path(config["document_root"]),
        )
        errors = installer.validate_plan(plan)
    except (OSError, TypeError, ValueError) as exc:
        print(f"Configuration validation failed: {exc}")
        return

    if errors:
        print()
        print("Configuration was not changed. The following problems were found:")
        for error in errors:
            print(f"  - {error}")
        return

    print()
    print("Proposed source folders:")
    for source in plan.source_directories:
        print(f"  - {source}")

    print()
    answer = input("Save these source folders? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Configuration unchanged.")
        return

    updated_config = dict(config)
    updated_config["source_directories"] = [
        str(source) for source in plan.source_directories
    ]

    try:
        installer._atomic_json_write(config_path, updated_config)
    except OSError as exc:
        print(f"Could not save configuration: {exc}")
        return

    print()
    print("Source folders updated successfully.")
    print("No documents were scanned, copied, moved or modified.")


@contextmanager
def _personal_profile_context(config: dict) -> Iterator[tuple[object, object, int, Path]]:
    """Bind profile operations to the active Personal installation only."""
    from pdfunlocker.profiles import manager, store

    database_directory = config.get("database_directory")
    profiles_directory = config.get("profiles_directory")
    profile_id_value = config.get("profile_id")

    if not isinstance(database_directory, str) or not database_directory.strip():
        raise RuntimeError("Personal database directory is missing.")
    if not isinstance(profiles_directory, str) or not profiles_directory.strip():
        raise RuntimeError("Personal profiles directory is missing.")

    try:
        profile_id = int(profile_id_value)
    except (TypeError, ValueError):
        raise RuntimeError("The configured Personal profile ID is invalid.") from None

    if profile_id < 1:
        raise RuntimeError("The configured Personal profile ID is invalid.")

    db_path = Path(database_directory).expanduser().resolve() / "profiles.sqlite3"
    profile_directory = Path(profiles_directory).expanduser().resolve()
    profile_path = profile_directory / f"profile{profile_id:02d}.env"

    old_db_path = store.DB_PATH
    old_profiles_dir = manager.PROFILES_DIR
    old_sequence_file = manager.SEQUENCE_FILE

    try:
        store.DB_PATH = db_path
        manager.PROFILES_DIR = profile_directory
        manager.SEQUENCE_FILE = profile_directory / "profile_sequence.txt"

        records = store.list_profiles()
        matching = [
            record for record in records
            if int(record["profile_id"]) == profile_id
        ]

        if len(matching) != 1:
            raise RuntimeError(
                "The configured Personal profile was not found exactly once "
                "in the Personal database."
            )

        if matching[0]["name"].strip().casefold() != "personal":
            raise RuntimeError(
                "The configured profile is not named Personal. "
                "No profile data was changed."
            )

        saved_path = matching[0].get("legacy_path", "")
        if saved_path:
            try:
                resolved_saved_path = Path(saved_path).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                raise RuntimeError(
                    "The Personal profile export path is invalid."
                ) from None

            if resolved_saved_path != profile_path.resolve():
                raise RuntimeError(
                    "The Personal database references a profile export "
                    "outside its configured location. Refusing to access it."
                )

        yield manager, store, profile_id, profile_path
    finally:
        store.DB_PATH = old_db_path
        manager.PROFILES_DIR = old_profiles_dir
        manager.SEQUENCE_FILE = old_sequence_file


def _profile_command(action: str) -> None:
    active = _require_active_config()
    if active is None:
        return

    _, config = active

    try:
        with _personal_profile_context(config) as (
            manager,
            store,
            profile_id,
            profile_path,
        ):
            if action == "show":
                manager.show_profile(profile_id)
                return

            if action == "edit":
                manager.modify_profile(profile_id)
                return

            if action == "reset":
                values = store.load_profile(profile_id)
                if values is None:
                    print("Personal profile not found. Nothing was changed.")
                    return

                print("Reset Personal profile")
                print("======================")
                print("This will permanently clear all saved profile field values.")
                print("The profile ID and profile name will be retained.")
                print(f"Profile ID: {profile_id}")
                print(f"Profile name: {values.get('PROFILE_NAME', 'Personal')}")
                print()
                answer = input("Type RESET to confirm: ").strip()

                if answer != "RESET":
                    print("Profile reset cancelled. No data was changed.")
                    return

                retained_values = {
                    "PROFILE_ID": str(profile_id),
                    "PROFILE_NAME": "Personal",
                }
                manager.save_env(profile_path, retained_values)
                print()
                print("Personal profile values have been reset.")
                print("Profile ID and name were retained.")
                print("Field definitions and sequence counters were preserved.")
                return

    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Profile operation failed: {exc}")


def command_profile_show(_: argparse.Namespace) -> None:
    _profile_command("show")


def command_profile_edit(_: argparse.Namespace) -> None:
    _profile_command("edit")


def command_profile_reset(_: argparse.Namespace) -> None:
    _profile_command("reset")


def command_setup(_: argparse.Namespace) -> None:
    active_config = installer.find_installation_config()
    if active_config is not None:
        print("PDF Unlocker is already initialized.")
        print(f"Active configuration: {active_config}")
        print("Setup was not restarted and no files were changed.")
        return

    installer.run_setup()


@contextmanager
def _personal_rules_context(config: dict) -> Iterator[object]:
    """Bind read-only rule operations to the active Personal rules directory."""
    from pdfunlocker.rules import manager

    configured_directory = config.get("rules_directory")
    if not isinstance(configured_directory, str) or not configured_directory.strip():
        raise RuntimeError("Personal rules directory is missing.")

    rules_directory = Path(configured_directory).expanduser().resolve()
    if not rules_directory.is_dir():
        raise RuntimeError(
            f"Personal rules directory does not exist or is not a directory: "
            f"{rules_directory}"
        )

    previous_directory = manager.RULES_DIR
    try:
        manager.RULES_DIR = rules_directory
        yield manager
    finally:
        manager.RULES_DIR = previous_directory


def _rules_command(action: str, rule_reference: str | None = None) -> None:
    active = _require_active_config()
    if active is None:
        return

    _, config = active
    try:
        with _personal_rules_context(config) as manager:
            if action == "list":
                manager.list_rules()
                return

            if action == "show":
                if not rule_reference:
                    print("A rule number or rule ID is required.")
                    return
                manager.show_rule(rule_reference)
                return

            if action == "validate":
                _validate_personal_rules(manager)
                return

            print(f"Unknown rules action: {action}")

    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Rules operation failed: {exc}")


def _validate_personal_rules(manager: object) -> None:
    """Validate active Personal rules without modifying any files."""
    rules_directory = manager.RULES_DIR
    paths = manager._rule_paths(root=rules_directory)

    if not paths:
        print("No active rules found. Nothing to validate.")
        return

    errors: list[str] = []
    parsed_rules = []

    for path in paths:
        try:
            parsed_rules.append(manager._parse_rule(path))
        except (manager.RuleError, OSError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")

    valid_rules = parsed_rules
    seen_numbers: dict[str, str] = {}
    seen_ids: dict[str, str] = {}
    seen_priorities: dict[str, str] = {}
    seen_patterns: dict[object, str] = {}

    for rule in valid_rules:
        previous = seen_numbers.get(rule.number)
        if previous is not None:
            errors.append(
                f"{rule.path.name}: duplicate rule number {rule.number} "
                f"(also used by {previous})"
            )
        else:
            seen_numbers[rule.number] = rule.path.name

        normalized_id = rule.rule_id.casefold()
        previous = seen_ids.get(normalized_id)
        if previous is not None:
            errors.append(
                f"{rule.path.name}: duplicate rule ID {rule.rule_id} "
                f"(also used by {previous})"
            )
        else:
            seen_ids[normalized_id] = rule.path.name

        if rule.priority != "Z":
            previous = seen_priorities.get(rule.priority)
            if previous is not None:
                errors.append(
                    f"{rule.path.name}: duplicate executable priority "
                    f"{rule.priority} (also used by {previous})"
                )
            else:
                seen_priorities[rule.priority] = rule.path.name

        if rule.fields:
            pattern = (
                "fields",
                tuple(
                    (part.field_id, part.mode, part.count)
                    for part in rule.fields
                ),
            )
        else:
            pattern = ("components", tuple(rule.components))

        signature = (pattern, tuple(sorted(set(rule.cases or (rule.case,)))))
        previous = seen_patterns.get(signature)
        if previous is not None:
            errors.append(
                f"{rule.path.name}: duplicate candidate-generation pattern "
                f"(also used by {previous})"
            )
        else:
            seen_patterns[signature] = rule.path.name

    print("Personal Rules Validation")
    print("=========================")
    print(f"Rules directory : {rules_directory}")
    print(f"Rule files      : {len(paths)}")
    print(f"Parsed rules    : {len(parsed_rules)}")
    print(f"Errors          : {len(errors)}")

    if errors:
        print("\\nValidation failed:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("\\nAll active Personal rules are valid.")

    print("No rule files were changed.")


def command_rules_list(_: argparse.Namespace) -> None:
    _rules_command("list")


def show_rule_reference(reference: str) -> None:
    """Show a rule from the active Personal rules directory."""
    _rules_command("show", reference)


def command_rules_show(args: argparse.Namespace) -> None:
    _rules_command("show", args.rule_id)


def command_rules_validate(_: argparse.Namespace) -> None:
    _rules_command("validate")


def command_not_ready(args: argparse.Namespace) -> None:
    command = " ".join(args.command_path)
    print(f"'{command}' is not implemented yet.")
    print("The initial CLI and installation setup are being established first.")


def build_personal_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfunlocker",
        description="PDF Unlocker Personal Edition",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_version()}",
    )

    commands = parser.add_subparsers(dest="command")

    setup = commands.add_parser("setup", help="Run the first-run setup wizard")
    setup.set_defaults(func=command_setup)

    status = commands.add_parser("status", help="Show installation status")
    status.set_defaults(func=command_status)

    config = commands.add_parser("config", help="View or edit configuration")
    config_commands = config.add_subparsers(dest="config_command")

    config_show = config_commands.add_parser("show", help="Show configuration")
    config_show.set_defaults(func=command_config_show)

    config_edit = config_commands.add_parser("edit", help="Edit source folders")
    config_edit.set_defaults(func=command_config_edit)

    profile = commands.add_parser("profile", help="Manage the Personal profile")
    profile_commands = profile.add_subparsers(dest="profile_command")

    profile_actions = {
        "show": command_profile_show,
        "edit": command_profile_edit,
        "reset": command_profile_reset,
    }
    for action, callback in profile_actions.items():
        item = profile_commands.add_parser(action)
        item.set_defaults(func=callback)

    rules = commands.add_parser("rules", help="Inspect predefined rules")
    rules_commands = rules.add_subparsers(dest="rules_command")

    rules_list = rules_commands.add_parser("list", help="List active predefined rules")
    rules_list.set_defaults(func=command_rules_list)

    rules_validate = rules_commands.add_parser(
        "validate", help="Validate active predefined rules"
    )
    rules_validate.set_defaults(func=command_rules_validate)

    rule_show = rules_commands.add_parser("show", help="Show one predefined rule")
    rule_show.add_argument("rule_id", help="Rule number or rule ID")
    rule_show.set_defaults(func=command_rules_show)

    for action in ("scan", "unlock", "retry", "check-corrupted"):
        item = commands.add_parser(action)
        item.set_defaults(
            func=command_not_ready,
            command_path=(action,),
        )

    return parser


def main(argv: Sequence[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = build_personal_parser()

    if not arguments:
        if installer.find_installation_config() is None:
            installer.run_setup()
        else:
            _print_menu()
        return

    args = parser.parse_args(arguments)
    if not hasattr(args, "func"):
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
