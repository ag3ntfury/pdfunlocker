"""Centralized application paths.

PDF input/output may use Android shared storage. Private application data
defaults to Termux's private home directory.
"""
from __future__ import annotations

import json
from pathlib import Path

APP_DIR = Path.home() / ".pdfunlocker"
CONFIG_DIR = APP_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "config.json"


def read_config() -> dict:
    try:
        value = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def configured_path(key: str, default: Path) -> Path:
    value = read_config().get(key)
    if isinstance(value, str) and value.strip():
        return Path(value).expanduser()
    return default


DATABASE_DIR = configured_path("database_directory", APP_DIR / "database")
PROFILES_DIR = configured_path("profiles_directory", APP_DIR / "profiles")
RULES_DIR = configured_path("rules_directory", APP_DIR / "rules")
LOGS_DIR = configured_path("logs_directory", APP_DIR / "logs")
