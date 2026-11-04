from __future__ import annotations

from pathlib import Path

import yaml

from pdfunlocker.rules import manager
from tools.migrate_field_ids import migrate_rules


def test_rule_parser_accepts_alphanumeric_bank_ids_and_dob_formats(tmp_path, monkeypatch):
    path = tmp_path / "rule00001.yml"
    path.write_text(
        """rule:\n  number: '00001'\n  id: '00001'\n  name: Test\n  category: profile\n  priority: A1\npattern:\n  fields:\n    - field_id: '1200E'\n      slice: {mode: last, count: 4}\n    - field_id: '0600'\n      format: YYYY\n      slice: {mode: full}\ntransform:\n  case: upper\n""",
        encoding="utf-8",
    )
    rule = manager._parse_rule(path)
    assert rule.fields[0].field_id == "1200E"
    assert rule.fields[1].field_id == "0600"
    assert rule.fields[1].format == "YYYY"


def test_rule_migration_rewrites_legacy_ids_and_archives_originals(tmp_path):
    source = Path(__file__).resolve().parents[1] / "rules"
    for path in source.glob("rule*.yml"):
        (tmp_path / path.name).write_bytes(path.read_bytes())

    changed = migrate_rules(tmp_path)
    assert len(changed) == 12
    data = yaml.safe_load((tmp_path / "rule00001.yml").read_text(encoding="utf-8"))
    assert data["pattern"]["fields"] == [
        {"field_id": "0200", "slice": {"mode": "first", "count": 4}},
        {"field_id": "0600", "format": "DDMM", "slice": {"mode": "full"}},
    ]
    assert (tmp_path / "archive/pre-field-id-migration/rule00001.yml").is_file()


def test_candidate_resolution_uses_bank_public_id_and_dob_format(tmp_path, monkeypatch):
    from pdfunlocker.profiles import store
    from pdfunlocker.pdf.candidates import _resolve_field_part
    from pdfunlocker.rules.manager import FieldPart

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    profile_path = tmp_path / "profile02.env"
    store.save_profile(
        profile_path,
        {
            "PROFILE_ID": "2",
            "PROFILE_NAME": "Test",
            "DOB": "07031999",
            "BANK_1200A": "Example Bank",
            "BANK_1200E_01": "1234567890",
            "BANK_1200E_02": "9876543210",
        },
    )
    profile = store.load_profile(2)
    assert _resolve_field_part(FieldPart("0600", format="DDMM"), profile) == ["0703"]
    assert _resolve_field_part(FieldPart("0600", format="YYYY"), profile) == ["1999"]
    assert _resolve_field_part(FieldPart("1200E"), profile) == [
        "1234567890", "9876543210"
    ]
