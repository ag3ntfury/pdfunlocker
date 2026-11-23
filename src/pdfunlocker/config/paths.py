"""Canonical Android/Linux paths for PDF Unlocker Alpha 1.3.3."""

import json
from pathlib import Path

from pdfunlocker.setup.scan_locations import is_android


INTERNAL_DIRECTORIES = (
    "config",
    "database",
    "profiles",
    "rules",
    "learning",
    "storage/Original",
    "storage/Locked",
    "storage/Unlocked",
    "storage/Corrupted",
    "storage/Unsupported",
    "storage/Duplicates",
    "queue/Pending",
    "queue/Processing",
    "queue/Completed",
    "backups/Database",
    "backups/Configuration",
    "logs/Application",
    "logs/Scanner",
    "logs/Processing",
    "reports",
    "temp",
    "cache",
)

EXPORT_DIRECTORIES = (
    "Database/Manual",
    "Database/Automatic",
    "Profiles",
    "Reports",
    "Logs",
    "PDF-Records/Original",
    "PDF-Records/Locked",
    "PDF-Records/Unlocked",
    "PDF-Records/Corrupted",
    "PDF-Records/Unsupported",
    "PDF-Records/Duplicates",
)


def detect_environment():
    return "android" if is_android() else "linux"


def default_paths(environment=None, home=None):
    """Return fixed private application and public PDF-output paths."""
    home = Path(home or Path.home()).expanduser().resolve()
    environment = environment or detect_environment()

    if environment == "android":
        public_home = Path("/storage/emulated/0")
        pdf_storage_root = public_home / "Documents" / "PDFUnlocker"
    elif environment == "linux":
        public_home = home
        pdf_storage_root = home / "Documents" / "PDFUnlocker"
    else:
        raise ValueError(f"Unsupported environment: {environment}")

    installation = home / ".pdfunlocker"
    return {
        "environment": environment,
        "home": home,
        "public_home": public_home,
        "installation": installation,
        "pdf_storage_root": pdf_storage_root,
        "pdf_storage": pdf_storage_root,
        "processed": pdf_storage_root / "Processed",
        "exports": pdf_storage_root / "Export",
    }


def load_settings(installation):
    config = Path(installation).expanduser() / "config" / "settings.json"
    if not config.is_file():
        return {}
    try:
        value = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read application settings: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Application settings must be a JSON object.")
    return value


def resolve_paths(installation=None, settings=None):
    installation = Path(
        installation or Path(__file__).resolve().parents[3]
    ).expanduser().resolve()
    settings = settings if settings is not None else load_settings(installation)
    environment = settings.get("environment") if isinstance(settings, dict) else None
    defaults = default_paths(environment)
    configured = settings.get("paths", {}) if isinstance(settings, dict) else {}

    install = Path(configured.get("installation", installation)).expanduser().resolve()
    root_value = configured.get(
        "pdf_storage_root",
        configured.get("pdf_storage", defaults["pdf_storage_root"]),
    )
    pdf_root = Path(root_value).expanduser().resolve()
    processed = Path(configured.get("processed", pdf_root / "Processed")).expanduser().resolve()
    exports = Path(configured.get("exports", pdf_root / "Export")).expanduser().resolve()

    return {
        "installation": install,
        "config": install / "config",
        "database": install / "database" / "pdfunlocker.db",
        "profiles": install / "profiles",
        "rules": install / "rules",
        "learning": install / "learning",
        "storage": install / "storage",
        "original": install / "storage" / "Original",
        "locked": install / "storage" / "Locked",
        "unlocked_internal": install / "storage" / "Unlocked",
        "corrupted": install / "storage" / "Corrupted",
        "unsupported": install / "storage" / "Unsupported",
        "duplicates": install / "storage" / "Duplicates",
        "queue": install / "queue",
        "queue_pending": install / "queue" / "Pending",
        "queue_processing": install / "queue" / "Processing",
        "queue_completed": install / "queue" / "Completed",
        "backups": install / "backups",
        "database_backups": install / "backups" / "Database",
        "configuration_backups": install / "backups" / "Configuration",
        "logs": install / "logs",
        "reports": install / "reports",
        "temp": install / "temp",
        "cache": install / "cache",
        "pdf_storage_root": pdf_root,
        "pdf_storage": pdf_root,
        "processed": processed,
        "exports": exports,
        "database_manual_exports": exports / "Database" / "Manual",
        "database_automatic_exports": exports / "Database" / "Automatic",
        "profile_exports": exports / "Profiles",
        "export_reports": exports / "Reports",
        "export_logs": exports / "Logs",
        "pdf_record_exports": exports / "PDF-Records",
    }


def validate_path_relationships(installation, pdf_storage_root):
    installation = Path(installation).expanduser().resolve()
    pdf_storage_root = Path(pdf_storage_root).expanduser().resolve()
    if installation in (Path("/"), Path.home()):
        raise ValueError("Installation path cannot be the filesystem root or home directory.")
    if (
        installation == pdf_storage_root
        or installation in pdf_storage_root.parents
        or pdf_storage_root in installation.parents
    ):
        raise ValueError(
            "Installation and public PDF storage directories must be separate and non-overlapping."
        )
    return True


def create_internal_structure(installation):
    root = Path(installation).expanduser().resolve()
    for relative in INTERNAL_DIRECTORIES:
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def create_public_structure(pdf_storage_root):
    """Create only the two public top-level output directories and their exports."""
    root = Path(pdf_storage_root).expanduser().resolve()
    (root / "Processed").mkdir(parents=True, exist_ok=True)
    for relative in EXPORT_DIRECTORIES:
        (root / "Export" / relative).mkdir(parents=True, exist_ok=True)
    return root
