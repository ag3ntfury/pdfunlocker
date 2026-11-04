#!/usr/bin/env python3
"""Migrate existing YAML rules to permanent public field IDs."""
from __future__ import annotations

import shutil
from pathlib import Path
import yaml

RULE_UPDATES = {
    "rule00001.yml": [
        {"field_id": "0200", "slice": {"mode": "first", "count": 4}},
        {"field_id": "0600", "format": "DDMM", "slice": {"mode": "full"}},
    ],
    "rule00002.yml": [
        {"field_id": "1200E", "slice": {"mode": "full"}},
    ],
    "rule00003.yml": [
        {"field_id": "1000", "slice": {"mode": "full"}},
    ],
    "rule00004.yml": [
        {"field_id": "0600", "slice": {"mode": "full"}},
    ],
    "rule00005.yml": [
        {"field_id": "0700", "slice": {"mode": "full"}},
    ],
    "rule00006.yml": [
        {"field_id": "0200", "slice": {"mode": "first", "count": 4}},
        {"field_id": "0700", "slice": {"mode": "last", "count": 4}},
    ],
    "rule00007.yml": [
        {"field_id": "0300", "slice": {"mode": "first", "count": 4}},
        {"field_id": "0700", "slice": {"mode": "last", "count": 4}},
    ],
    "rule00008.yml": [
        {"field_id": "0200", "slice": {"mode": "first", "count": 4}},
        {"field_id": "1200D", "slice": {"mode": "full"}},
    ],
    "rule00009.yml": [
        {"field_id": "1200D", "slice": {"mode": "full"}},
    ],
    "rule00010.yml": [
        {"field_id": "1200E", "slice": {"mode": "first", "count": 6}},
    ],
    "rule00011.yml": [
        {"field_id": "0600", "slice": {"mode": "full"}},
        {"field_id": "1000", "slice": {"mode": "full"}},
    ],
    "rule05000.yml": [
        {"field_id": "0200", "slice": {"mode": "first", "count": 4}},
        {"field_id": "0600", "format": "YYYY", "slice": {"mode": "full"}},
    ],
}


def migrate_rules(rules_dir: Path) -> list[Path]:
    changed: list[Path] = []
    backup_dir = rules_dir / "archive" / "pre-field-id-migration"
    for filename, fields in RULE_UPDATES.items():
        path = rules_dir / filename
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("pattern"), dict):
            raise RuntimeError(f"Cannot migrate malformed rule: {path}")
        current = data["pattern"].get("fields")
        if current == fields:
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / filename
        if not backup.exists():
            shutil.copy2(path, backup)
        data["pattern"].pop("components", None)
        data["pattern"]["fields"] = fields
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000),
            encoding="utf-8",
        )
        changed.append(path)
    return changed


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("rules_dir", type=Path)
    args = parser.parse_args()
    for path in migrate_rules(args.rules_dir):
        print(f"UPDATED {path}")
    print("Rule field-ID migration complete.")
