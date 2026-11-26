"""Automatic installer and setup commands for PDF Unlocker Alpha 1.3.3."""

import argparse
import json
import os
import platform
import shlex
import shutil
import sys
from datetime import datetime
from pathlib import Path

from pdfunlocker import __version__
from pdfunlocker.cli.profiles import add_profile_commands
from pdfunlocker.config.paths import (
    create_internal_structure,
    create_public_structure,
    default_paths,
    resolve_paths,
    validate_path_relationships,
)
from pdfunlocker.database.backup import migrate_database
from pdfunlocker.setup.scan_locations import is_android, select_scan_locations


APP_DIRECTORIES = ("src", "templates", "docs", "scripts")
RUNTIME_DATA_DIRECTORIES = (
    "profiles",
    "rules",
    "learning",
    "backups",
    "logs",
    "storage",
    "queue",
    "reports",
    "temp",
    "cache",
)
DATABASE_NAME = "pdfunlocker.db"


def detect_environment():
    if is_android():
        return "android", "Android (Termux)"
    if platform.system().lower() == "linux":
        return "linux", "Linux"
    return "unknown", platform.system()


def get_default_paths():
    environment, environment_name = detect_environment()
    defaults = default_paths(environment)
    return {
        "environment": environment,
        "environment_name": environment_name,
        "install_path": defaults["installation"],
        "pdf_storage_root": defaults["pdf_storage_root"],
        "processed": defaults["processed"],
        "exports": defaults["exports"],
    }


def is_inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def validate_directory_relationships(install_path, pdf_storage_root):
    try:
        validate_path_relationships(install_path, pdf_storage_root)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def prepare_pdf_storage(pdf_storage_root):
    return create_public_structure(pdf_storage_root)


def _copy_missing_tree(source, destination, excluded_files=None):
    """Copy missing user data without replacing existing destination files."""
    source = Path(source)
    destination = Path(destination)
    excluded_files = set(excluded_files or ())
    if not source.is_dir() or source.is_symlink():
        return

    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_symlink():
            continue
        target = destination / item.name
        if item.is_dir():
            _copy_missing_tree(item, target, excluded_files)
        elif item.is_file() and item.name not in excluded_files and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def copy_application(source, destination):
    """Install application code and migrate missing user data without overwrites."""
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)

    if source != destination:
        for name in APP_DIRECTORIES:
            source_dir = source / name
            if source_dir.is_dir() and not source_dir.is_symlink():
                shutil.copytree(
                    source_dir,
                    destination / name,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git"),
                )

        for name in ("pyproject.toml", "README.md", "LICENSE"):
            item = source / name
            if item.is_file() and not item.is_symlink():
                shutil.copy2(item, destination / name)

        # Preserve settings if the destination has none. Existing destination
        # settings always take precedence and are backed up before setup updates.
        source_config = source / "config"
        target_config = destination / "config"
        if source_config.is_dir():
            target_config.mkdir(parents=True, exist_ok=True)
            for item in source_config.iterdir():
                if item.is_symlink():
                    continue
                target = target_config / item.name
                if item.name == "settings.json":
                    if not target.exists() and item.is_file():
                        shutil.copy2(item, target)
                elif item.is_dir():
                    _copy_missing_tree(item, target)
                elif item.is_file() and not target.exists():
                    shutil.copy2(item, target)

        # User-owned runtime content is copied only when the destination file
        # does not exist. This preserves profiles, learning state, rules, logs,
        # backups and private PDF data without destructive merging.
        for name in RUNTIME_DATA_DIRECTORIES:
            excluded = {"rule00000.yml"} if name == "rules" else None
            _copy_missing_tree(
                source / name,
                destination / name,
                excluded_files=excluded,
            )

    create_internal_structure(destination)
    if not (destination / "src/pdfunlocker/cli/main.py").is_file():
        raise RuntimeError("Application copy verification failed.")
    print(f"Application files ready in: {destination}")
    return destination


def register_launcher(install_path):
    if is_android():
        prefix = os.environ.get("PREFIX")
        if not prefix:
            raise RuntimeError("Termux PREFIX is unavailable; cannot register launcher.")
        bin_dir = Path(prefix) / "bin"
    else:
        bin_dir = Path.home() / ".local" / "bin"

    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "pdfunlocker"
    launcher.write_text(
        "#!/bin/sh\n"
        + f"PROJECT={shlex.quote(str(Path(install_path).resolve()))}\n"
        + 'cd "$PROJECT" || exit 1\n'
        + 'export PYTHONPATH="$PROJECT/src"\n'
        + f"exec {shlex.quote(sys.executable)} -m pdfunlocker \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    print(f"Command registered: pdfunlocker ({launcher})")
    return launcher


def load_settings(config_file):
    config_file = Path(config_file)
    if not config_file.is_file():
        return {}
    try:
        value = json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read existing configuration safely: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Existing settings must contain a JSON object.")
    return value


def backup_settings(config_file):
    config_file = Path(config_file)
    if not config_file.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = config_file.with_name(f"settings.json.before-v1.3-{stamp}")
    shutil.copy2(config_file, backup)
    return backup


def save_settings(config_file, settings):
    config_file = Path(config_file)
    existing = load_settings(config_file)
    existing.update(settings)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_file.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_file)


def _database_candidates(source_install, target_install):
    source_install = Path(source_install).resolve()
    target_install = Path(target_install).resolve()
    target = target_install / "database" / DATABASE_NAME
    canonical = source_install / "database" / DATABASE_NAME
    legacy = [
        source_install / "data" / "database" / DATABASE_NAME,
        target_install / "data" / "database" / DATABASE_NAME,
    ]
    legacy = list(
        dict.fromkeys(
            item.resolve()
            for item in legacy
            if item.resolve() != target and item.is_file()
        )
    )
    return target, canonical, legacy


def migrate_existing_database(source_install, target_install):
    """Copy the canonical DB first; use a single legacy DB only as fallback."""
    target, canonical, legacy = _database_candidates(source_install, target_install)

    if target.is_file():
        if target == canonical:
            return {"database": target, "migrated_from": None}
        if canonical.is_file() or legacy:
            raise RuntimeError(
                "Destination database already exists alongside another database "
                "candidate. No database was overwritten; reconcile them first."
            )
        return {"database": target, "migrated_from": None}

    if canonical.is_file():
        return {
            "database": migrate_database(canonical, target),
            "migrated_from": canonical,
        }

    if len(legacy) > 1:
        raise RuntimeError(
            "Multiple legacy databases found; no automatic choice was made: "
            + ", ".join(map(str, legacy))
        )
    if legacy:
        return {
            "database": migrate_database(legacy[0], target),
            "migrated_from": legacy[0],
        }
    return {"database": target, "migrated_from": None}


def _scan_settings(environment, pdf_storage_root, install_path):
    return select_scan_locations(
        environment,
        pdf_storage_root,
        installation=install_path,
        default=False,
        home=Path.home(),
    )


def _write_scan_settings(install_path, settings, scan_settings):
    config_file = Path(install_path) / "config" / "settings.json"
    existing = load_settings(config_file)

    paths = dict(existing.get("paths", {}))
    defaults = default_paths(settings["environment"])
    paths.update({
        "installation": str(install_path),
        "pdf_storage_root": str(defaults["pdf_storage_root"]),
        "pdf_storage": str(defaults["pdf_storage_root"]),
        "processed": str(defaults["processed"]),
        "exports": str(defaults["exports"]),
    })

    setup_state = dict(existing.get("setup", {}))
    setup_state.update({
        "paths_configured": True,
        "scan_locations_configured": True,
        "installer_stage_completed": True,
        "installer_stage": "scan_configured",
        "completed": False,
    })
    setup_state.setdefault("database_initialized", (Path(install_path) / "database" / DATABASE_NAME).is_file())
    setup_state.setdefault("profile_configured", False)

    updated = dict(existing)
    updated.update({
        "environment": settings["environment"],
        "paths": paths,
        "scan": scan_settings,
        "setup": setup_state,
    })

    backup = backup_settings(config_file)
    save_settings(config_file, updated)
    return backup




def run_profile_setup(install_path, config_file):
    """Create or reuse profiles and mark installation complete safely."""
    from pdfunlocker.cli import profiles as profile_cli
    from pdfunlocker.profiles.store import initialize_database, list_profiles

    install_path = Path(install_path).expanduser().resolve()
    config_file = Path(config_file)
    database = install_path / "database" / DATABASE_NAME

    print()
    print("===== PROFILE SETUP =====")
    initialize_database(database)

    profiles = list_profiles(database)

    if profiles:
        print("Existing profiles found. They will be preserved.")
    else:
        print("No profiles exist. At least one enabled profile is required.")
        created = profile_cli.create_profile_interactive(root=install_path)
        if created is None:
            print("Profile setup cancelled. Installation remains incomplete.")
            return 1

    while True:
        profiles = list_profiles(database)
        enabled = [item for item in profiles if item["enabled"]]

        if not enabled:
            print()
            print("No enabled profiles are available.")
            print("Enable a profile using: pdfunlocker profile edit PROFILE_ID")
            print("Then run 'pdfunlocker setup' again.")
            return 1

        answer = profile_cli.prompt("Add another profile? [y/N]: ")
        if answer is None or answer.lower() not in ("y", "yes"):
            break

        created = profile_cli.create_profile_interactive(root=install_path)
        if created is None:
            print("Additional profile creation cancelled.")
            break

    profiles = list_profiles(database)
    enabled = [item for item in profiles if item["enabled"]]

    print()
    print("===== PROFILE EXECUTION ORDER =====")
    for item in profiles:
        status = "Enabled" if item["enabled"] else "Disabled"
        print(
            f"{item['execution_order']}. {item['profile_id']} "
            f"- {item['name']} [{status}]"
        )

    if not enabled:
        print("Installation remains incomplete: no enabled profile.")
        return 1

    confirmation = profile_cli.prompt("Confirm this execution order? [Y/n]: ")
    if confirmation is None or confirmation.lower() not in ("", "y", "yes"):
        print("Execution order not confirmed. Installation remains incomplete.")
        print("Review the order with: pdfunlocker profile list")
        print("Change it with: pdfunlocker profile edit PROFILE_ID")
        return 1

    existing = load_settings(config_file)
    setup_state = dict(existing.get("setup", {}))
    setup_state.update({
        "paths_configured": True,
        "scan_locations_configured": True,
        "database_initialized": True,
        "profile_configured": True,
        "installer_stage": "profile_configured",
        "installer_stage_completed": True,
        "completed": True,
    })

    backup = backup_settings(config_file)
    save_settings(config_file, {"setup": setup_state})

    if backup:
        print(f"Previous settings backup: {backup}")

    print()
    print("Profile setup completed.")
    print("Installation status: COMPLETE")
    print("Enabled profiles will be available in execution order.")
    return 0


def run_setup(args=None):
    """Automatic installation followed by the required profile stage."""
    defaults = get_default_paths()
    environment = defaults["environment"]
    if environment not in ("android", "linux"):
        raise RuntimeError(f"Unsupported environment: {defaults['environment_name']}")

    source_install = Path(__file__).resolve().parents[3]
    install_path = Path(defaults["install_path"]).expanduser().resolve()
    pdf_storage_root = Path(defaults["pdf_storage_root"]).expanduser().resolve()

    validate_directory_relationships(install_path, pdf_storage_root)

    print("\nPDF Unlocker — Alpha 1.3.3 Installer")
    print("====================================")
    print(f"Detected environment: {defaults['environment_name']}")
    print(f"Application directory: {install_path}")
    print(f"Public PDF directory: {pdf_storage_root}")
    print("Installation paths are automatic; no manual path selection is available.")

    if install_path.exists() and not install_path.is_dir():
        raise RuntimeError("The application installation path exists and is not a directory.")
    if source_install != install_path and is_inside(install_path, source_install):
        raise RuntimeError("The destination installation cannot be inside the source project.")

    print("\n===== SCAN LOCATION SETUP =====")
    scan_settings = _scan_settings(environment, pdf_storage_root, install_path)
    if not isinstance(scan_settings, dict) or not scan_settings.get("locations"):
        raise RuntimeError("At least one valid scan location must be selected.")

    exclusions = set(scan_settings.get("exclude_paths", []))
    exclusions.add(str(install_path))
    exclusions.add(str(pdf_storage_root))
    if source_install != install_path:
        exclusions.add(str(source_install))
    scan_settings["exclude_paths"] = sorted(exclusions)

    # Prepare the target without overwriting user-owned files.
    copy_application(source_install, install_path)
    create_internal_structure(install_path)
    create_public_structure(pdf_storage_root)

    migration = migrate_existing_database(source_install, install_path)
    config_file = install_path / "config" / "settings.json"
    existing = load_settings(config_file)

    # Existing settings, profiles, learning records and backups remain intact.
    # A fresh installation remains incomplete until the later profile stage.
    old_setup = existing.get("setup", {})
    if not isinstance(old_setup, dict):
        old_setup = {}
    setup_state = dict(old_setup)
    setup_state.update({
        "paths_configured": True,
        "scan_locations_configured": True,
        "installer_stage_completed": True,
        "installer_stage": "scan_configured",
        "database_initialized": migration["database"].is_file(),
        "profile_configured": False,  # Alpha 1.3.3 deliberately stops before profile setup.
        "completed": False,
    })

    settings = {
        "environment": environment,
        "paths": {
            "installation": str(install_path),
            "pdf_storage_root": str(pdf_storage_root),
            "pdf_storage": str(pdf_storage_root),
            "processed": str(pdf_storage_root / "Processed"),
            "exports": str(pdf_storage_root / "Export"),
        },
        "scan": scan_settings,
        "setup": setup_state,
    }

    settings_backup = backup_settings(config_file)
    save_settings(config_file, settings)
    launcher = register_launcher(install_path)

    print("\n===== AUTOMATIC INSTALLATION COMPLETE =====")
    print(f"Application: {install_path}")
    print(f"Database: {migration['database']}")
    if migration["migrated_from"]:
        print(f"Database copied safely from: {migration['migrated_from']}")
        print("Original database retained unchanged.")

    print(f"Public PDF storage: {pdf_storage_root}")
    print(f"Processed PDFs: {pdf_storage_root / 'Processed'}")
    print(f"Exports: {pdf_storage_root / 'Export'}")

    print("\nSelected scan locations:")
    for item in scan_settings["locations"]:
        print(f"  {item}")

    print("\nExcluded paths:")
    for item in scan_settings["exclude_paths"]:
        print(f"  {item}")

    if settings_backup:
        print(f"Previous settings backup: {settings_backup}")

    print(f"Launcher: {launcher}")
    print("Source PDFs were not moved, renamed or deleted.")

    return 0


def run_scan_configure(args=None):
    """Change scan roots without reinstalling or changing other user data."""
    install_path = Path(__file__).resolve().parents[3]
    config_file = install_path / "config" / "settings.json"
    settings = load_settings(config_file)

    environment = settings.get("environment")
    if environment not in ("android", "linux"):
        environment, _ = detect_environment()

    resolved = resolve_paths(install_path, settings)
    pdf_storage_root = resolved["pdf_storage_root"]

    print("\nPDF Unlocker — Scan Location Configuration")
    scan_settings = _scan_settings(environment, pdf_storage_root, install_path)
    exclusions = set(scan_settings.get("exclude_paths", []))
    exclusions.add(str(install_path))
    exclusions.add(str(pdf_storage_root))
    scan_settings["exclude_paths"] = sorted(exclusions)

    updated = dict(settings)
    updated["environment"] = environment
    updated["scan"] = scan_settings
    setup_state = dict(updated.get("setup", {}))
    setup_state["scan_locations_configured"] = True
    setup_state["installer_stage"] = "scan_configured"
    setup_state["installer_stage_completed"] = True
    setup_state["completed"] = False
    updated["setup"] = setup_state

    backup = backup_settings(config_file)
    save_settings(config_file, updated)

    print("\nScan locations updated:")
    for location in scan_settings["locations"]:
        print(f"  {location}")
    if backup:
        print(f"Previous settings backup: {backup}")
    print("Application files, database and profile data were not changed.")
    return 0


def run_database_export(args=None):
    install_path = Path(__file__).resolve().parents[3]
    settings = load_settings(install_path / "config" / "settings.json")
    resolved = resolve_paths(install_path, settings)
    from pdfunlocker.database.backup import export_database

    result = export_database(
        resolved["database"],
        resolved["pdf_storage_root"],
        kind="automatic" if args and args.automatic else "manual",
        recovery_directory=resolved["database_backups"],
        export_root=resolved["exports"],
    )
    print(f"Database export created: {result['export']}")
    print(f"Private recovery snapshot: {result['recovery']}")


def main():
    parser = argparse.ArgumentParser(prog="pdfunlocker", description="PDF Unlocker")
    parser.add_argument("--version", action="version", version=f"pdfunlocker {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser("setup", help="Run automatic installation and scan setup")
    setup_parser.set_defaults(func=run_setup)
    install_parser = subparsers.add_parser("install", help="Alias for automatic setup")
    install_parser.set_defaults(func=run_setup)

    scan_parser = subparsers.add_parser("scan", help="Manage PDF scan locations")
    scan_commands = scan_parser.add_subparsers(dest="scan_command", required=True)
    configure_parser = scan_commands.add_parser("configure", help="Change scan locations")
    configure_parser.set_defaults(func=run_scan_configure)

    add_profile_commands(subparsers)

    database_parser = subparsers.add_parser("database", help="Database maintenance")
    database_commands = database_parser.add_subparsers(dest="database_command", required=True)
    export_parser = database_commands.add_parser("export", help="Create a verified database export")
    export_parser.add_argument("--automatic", action="store_true")
    export_parser.set_defaults(func=run_database_export)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    try:
        result = args.func(args)
        return result if isinstance(result, int) else 0
    except (RuntimeError, ValueError, OSError, FileNotFoundError, FileExistsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
