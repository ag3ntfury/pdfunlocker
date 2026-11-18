import argparse
import json
import os
import platform
import re
import shlex
import shutil
import sys
from pathlib import Path

from pdfunlocker import __version__
from pdfunlocker.cli.profiles import (
    add_profile_commands,
    create_profile_interactive,
)
from pdfunlocker.profiles.store import initialize_database, list_profiles
import sqlite3
from pdfunlocker.setup.scan_locations import (
    is_android,
    select_scan_locations,
)


PDF_STORAGE_FOLDERS = [
    "Inbox",
    "Original",
    "Unlocked",
    "Locked",
    "Unsupported",
    "Duplicates",
    "Export/Profiles",
    "Export/Database",
]

APP_DIRECTORIES = [
    "src",
    "templates",
    "rules",
    "docs",
    "scripts",
]


def detect_environment():
    if is_android():
        return "android", "Android (Termux)"
    if platform.system().lower() == "linux":
        return "linux", "Linux"
    return "unknown", platform.system()


def get_default_paths():
    environment, environment_name = detect_environment()
    home = Path.home()

    pdf_storage = (
        Path("/storage/emulated/0/PDFUnlocker")
        if environment == "android"
        else home / "PDFUnlocker"
    )

    return {
        "environment": environment,
        "environment_name": environment_name,
        "install_path": home / "pdfunlocker",
        "pdf_storage": pdf_storage,
    }


def ask_path(label, default):
    while True:
        raw = input(f"{label} [{default}]: ").strip()

        if not raw:
            return default.resolve()

        if any(char in raw for char in ("\x00", "\n", "\r", "[", "]")):
            print("Invalid path. Check for accidental brackets or control characters.")
            continue

        try:
            return Path(raw).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            print("Invalid path. Please enter a valid directory path.")


def is_inside(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_directory_relationships(install_path, pdf_storage):
    if install_path == Path("/") or install_path == Path.home():
        raise RuntimeError(
            "The installation directory cannot be the root or home directory."
        )

    if (
        pdf_storage == install_path
        or is_inside(pdf_storage, install_path)
        or is_inside(install_path, pdf_storage)
    ):
        raise RuntimeError(
            "Installation and PDF storage directories must be separate."
        )


def prepare_pdf_storage(pdf_storage):
    pdf_storage.mkdir(parents=True, exist_ok=True)

    if not pdf_storage.is_dir():
        raise RuntimeError("PDF storage path is not a directory.")

    if not os.access(pdf_storage, os.R_OK | os.W_OK | os.X_OK):
        raise RuntimeError(
            "PDF storage directory is not accessible or writable."
        )

    for folder in PDF_STORAGE_FOLDERS:
        path = pdf_storage / folder
        path.mkdir(parents=True, exist_ok=True)

        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise RuntimeError(f"Folder is not writable: {path}")

    print(f"\nPDF storage ready: {pdf_storage}")


def copy_application(source, destination):
    destination.mkdir(parents=True, exist_ok=True)

    for name in APP_DIRECTORIES:
        source_dir = source / name

        if source_dir.is_dir():
            shutil.copytree(
                source_dir,
                destination / name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".git"
                ),
            )

    for name in ("pyproject.toml", "README.md", "LICENSE"):
        source_file = source / name

        if source_file.is_file():
            shutil.copy2(source_file, destination / name)

    source_config = source / "config"
    destination_config = destination / "config"
    destination_config.mkdir(exist_ok=True)

    if source_config.is_dir():
        for item in source_config.iterdir():
            if item.name == "settings.json":
                continue

            target = destination_config / item.name

            if item.is_dir():
                shutil.copytree(
                    item,
                    target,
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc"
                    ),
                )
            elif item.is_file():
                shutil.copy2(item, target)

    for name in ("database", "profiles", "logs", "temp", "exports"):
        (destination / name).mkdir(parents=True, exist_ok=True)

    required = destination / "src/pdfunlocker/cli/main.py"

    if not required.is_file():
        raise RuntimeError("Application copy verification failed.")

    print(f"Application files installed in: {destination}")


def register_launcher(install_path):
    if is_android():
        bin_dir = Path(os.environ["PREFIX"]) / "bin"
    else:
        bin_dir = Path.home() / ".local" / "bin"

    bin_dir.mkdir(parents=True, exist_ok=True)

    command_name = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "",
        install_path.name.lower(),
    )

    if not command_name:
        raise RuntimeError(
            "Cannot create a command name from this directory."
        )

    launcher = bin_dir / command_name
    python_executable = shlex.quote(sys.executable)
    project_path = shlex.quote(str(install_path))

    launcher.write_text(
        "#!/bin/sh\n"
        f"PROJECT={project_path}\n"
        'cd "$PROJECT" || exit 1\n'
        'export PYTHONPATH="$PROJECT/src"\n'
        f"exec {python_executable} -m pdfunlocker \"$@\"\n",
        encoding="utf-8",
    )

    launcher.chmod(0o755)

    print(f"Command registered: {command_name}")
    return command_name


def save_settings(config_file, settings):
    config_file.parent.mkdir(parents=True, exist_ok=True)

    if config_file.exists():
        try:
            existing = json.loads(
                config_file.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(
                f"Cannot read existing configuration safely: {error}"
            )

        if not isinstance(existing, dict):
            raise RuntimeError(
                "Existing settings must contain a JSON object."
            )
    else:
        existing = {}

    existing.update(settings)

    temporary = config_file.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(config_file)


def run_setup(args=None):
    paths = get_default_paths()

    if paths["environment"] not in ("android", "linux"):
        raise RuntimeError(
            f"Unsupported environment: {paths['environment_name']}"
        )

    source_install = Path(__file__).resolve().parents[3]

    print("\nPDF Unlocker - Setup")
    print("====================")
    print(f"Detected environment: {paths['environment_name']}")

    print("\n===== DIRECTORY SETTINGS =====")

    install_path = ask_path(
        "Installation directory",
        source_install,
    )

    if install_path == Path("/") or install_path == Path.home():
        raise RuntimeError(
            "That installation directory is not allowed."
        )

    if install_path != source_install:
        if is_inside(install_path, source_install):
            raise RuntimeError(
                "A new installation cannot be created inside "
                "the current installation."
            )

        if install_path.exists() and not install_path.is_dir():
            raise RuntimeError(
                "Installation path exists and is not a directory."
            )

        if install_path.exists() and any(install_path.iterdir()):
            answer = input(
                f"\n{install_path} already contains files. "
                "Merge application files into this directory? [y/N]: "
            ).strip().lower()

            if answer not in ("y", "yes"):
                raise RuntimeError("Installation cancelled.")

        install_path.parent.mkdir(parents=True, exist_ok=True)
        copy_application(source_install, install_path)

    pdf_storage = ask_path(
        "PDF storage directory",
        paths["pdf_storage"],
    )

    validate_directory_relationships(install_path, pdf_storage)
    prepare_pdf_storage(pdf_storage)

    command_name = register_launcher(install_path)

    print("\n===== SCAN LOCATION SELECTION =====")

    scan_settings = select_scan_locations(
        paths["environment"],
        pdf_storage,
    )

    if (
        not isinstance(scan_settings, dict)
        or not isinstance(scan_settings.get("locations"), list)
        or not scan_settings["locations"]
    ):
        raise RuntimeError(
            "At least one valid scan location must be selected."
        )

    settings = {
        "environment": paths["environment"],
        "paths": {
            "installation": str(install_path),
            "pdf_storage": str(pdf_storage),
        },
        "scan": scan_settings,
        "setup": {
            "paths_configured": True,
            "scan_locations_configured": True,
            "database_initialized": False,
            "profile_configured": False,
            "completed": False,
        },
    }

    config_file = install_path / "config" / "settings.json"
    save_settings(config_file, settings)

    print("\n===== SCAN CONFIGURATION SAVED =====")
    print(f"Installation: {install_path}")
    print(f"PDF storage: {pdf_storage}")
    print(f"Configuration: {config_file}")

    print("\nSelected scan locations:")
    for location in scan_settings["locations"]:
        print(f"  {location}")

    print("\nRecursive scanning: enabled")
    print("Follow symbolic links: disabled")
    print("File type: PDF only")
    print("Duplicate detection: SHA-256")

    # Initialize the database without deleting existing profiles.
    print("\n===== DATABASE INITIALIZATION =====")
    database_path = install_path / "database" / "pdfunlocker.db"
    initialize_database(database_path)
    print(f"Database ready: {database_path}")

    # Record database initialization immediately, even if profile setup is cancelled.
    settings["setup"]["database_initialized"] = True
    save_settings(config_file, settings)

    # Require at least one enabled profile before completing setup.
    enabled_profiles = list_profiles(
        database_path,
        include_disabled=False,
    )

    if not enabled_profiles:
        print("\n===== FIRST PROFILE SETUP =====")
        print("At least one enabled profile is required to complete setup.")

        profile_id = create_profile_interactive(install_path)

        if not profile_id:
            raise RuntimeError(
                "Profile creation was cancelled. Installation remains incomplete. "
                "Run setup again to finish."
            )

    enabled_profiles = list_profiles(
        database_path,
        include_disabled=False,
    )

    if not enabled_profiles:
        raise RuntimeError(
            "No enabled profile exists. Enable or create a profile, then run setup again."
        )

    # Record profile configuration separately from final installation completion.
    settings["setup"]["profile_configured"] = True
    save_settings(config_file, settings)

    # Validate the final installation paths and required directories.
    if not (install_path / "src" / "pdfunlocker" / "__main__.py").is_file():
        raise RuntimeError("Application files are missing from the installation directory.")

    if not database_path.is_file():
        raise RuntimeError("Profile database initialization failed.")

    if not pdf_storage.is_dir():
        raise RuntimeError("PDF storage directory is missing.")

    for folder in PDF_STORAGE_FOLDERS:
        if not (pdf_storage / folder).is_dir():
            raise RuntimeError(f"Required PDF storage folder is missing: {folder}")

    # Mark setup complete only after every required stage succeeds.
    settings["setup"]["completed"] = True

    save_settings(config_file, settings)

    print("\n===== INSTALLATION COMPLETED =====")
    print(f"Installation: {install_path}")
    print(f"PDF storage: {pdf_storage}")
    print(f"Database: {database_path}")
    print(f"Enabled profiles: {len(enabled_profiles)}")
    print(f"Configuration: {config_file}")
    print(f"Command: {command_name}")
    print("\nPDF Unlocker is ready.")


def main():
    parser = argparse.ArgumentParser(
        prog="pdfunlocker",
        description="PDF Unlocker",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"pdfunlocker {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    setup_parser = subparsers.add_parser(
        "setup",
        help="Configure PDF Unlocker for first use",
    )
    setup_parser.set_defaults(func=run_setup)

    install_parser = subparsers.add_parser(
        "install",
        help="Alias for setup",
    )
    install_parser.set_defaults(func=run_setup)

    add_profile_commands(subparsers)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    try:
        args.func(args)
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"\nPDF UNLOCKER ERROR: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
