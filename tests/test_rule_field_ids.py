from __future__ import annotations

from pathlib import Path

from pdfunlocker.rules import manager


def test_rule_parser_accepts_legacy_bank_ids_and_dob_formats(tmp_path, monkeypatch):
    from pdfunlocker.profiles import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    path = tmp_path / "rule00001.yml"
    path.write_text(
        """rule:
  number: '00001'
  id: '00001'
  name: Test
  category: profile
  priority: A1
pattern:
  fields:
    - field_id: '1200E'
      slice: {mode: last, count: 4}
    - field_id: '0600'
      format: YYYY
      slice: {mode: full}
transform:
  case: upper
""",
        encoding="utf-8",
    )
    rule = manager._parse_rule(path)
    assert rule.fields[0].field_id == "4424"
    assert rule.fields[1].field_id == "1506"
    assert rule.fields[1].format == "YYYY"


def test_candidate_resolution_uses_shared_bank_type_id_and_dob_format(tmp_path, monkeypatch):
    from pdfunlocker.profiles import store
    from pdfunlocker.pdf.candidates import _resolve_field_part
    from pdfunlocker.rules.manager import FieldPart

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    store.ensure_bank_group(1201)
    profile_path = tmp_path / "profile02.env"
    values = {
        "PROFILE_ID": "2",
        "PROFILE_NAME": "Test",
        "DOB": "07031999",
        "BANK_1200A": "SBI",
        "BANK_1200E_01": "1234567890",
        "BANK_1200E_02": "9876543210",
        "BANK_1201A": "HDFC",
        "BANK_1201E_03": "111122223333",
    }
    store.save_profile(profile_path, values)
    profile = store.load_profile(2)
    assert _resolve_field_part(FieldPart("0600", format="DDMM"), profile) == ["0703"]
    assert _resolve_field_part(FieldPart("0600", format="YYYY"), profile) == ["1999"]
    legacy_date_profile = {"BIRTH_DAY": "07", "BIRTH_MONTH": "03", "BIRTH_YEAR": "1999"}
    assert _resolve_field_part(FieldPart("009"), legacy_date_profile) == ["07"]
    assert _resolve_field_part(FieldPart("010"), legacy_date_profile) == ["03"]
    assert _resolve_field_part(FieldPart("011"), legacy_date_profile) == ["1999"]
    assert _resolve_field_part(FieldPart("1200E"), profile) == [
        "1234567890", "9876543210", "111122223333"
    ]


def test_bank_field_registry_is_deduplicated_for_rule_builder(tmp_path, monkeypatch):
    from pdfunlocker.profiles import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    store.ensure_bank_group(1201)
    fields = manager._profile_fields()
    bank_ids = [item["field_id"] for item in fields if item["field_id"] in {"4169", "4223", "4298", "4356", "4424", "4487"}]
    # The internal store has one definition per bank, but the public rule
    # registry should present one entry per shared field type.
    assert len(set(bank_ids)) == 6


def test_rule_parser_rejects_unassigned_and_value_instance_ids(tmp_path, monkeypatch):
    import pytest
    from pdfunlocker.profiles import store
    from pdfunlocker.rules.manager import RuleError

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()

    template = """rule:
  number: '00002'
  id: '00002'
  name: Test
  category: profile
  priority: A1
pattern:
  fields:
    - field_id: '{field_id}'
transform:
  case: upper
"""
    for field_id in ("2500", "9999", "4169A", "4169ZZ"):
        path = tmp_path / f"rule-{field_id}.yml"
        path.write_text(template.format(field_id=field_id), encoding="utf-8")
        with pytest.raises(RuleError, match="unknown, unassigned, or invalid field_id"):
            manager._parse_rule(path)


def test_rule_parser_accepts_registered_custom_numeric_field_id(tmp_path, monkeypatch):
    from pdfunlocker.profiles import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    _, key = store.add_field("Company Alias", "COMPANY_ALIAS", True, "Business")
    custom = next(
        item["field_id"] for item in store.list_fields(include_archived=True)
        if item["field_key"] == key
    )
    path = tmp_path / "rule00003.yml"
    path.write_text(
        f"""rule:
  number: '00003'
  id: '00003'
  name: Test
  category: profile
  priority: A1
pattern:
  fields:
    - field_id: '{custom}'
transform:
  case: upper
""",
        encoding="utf-8",
    )
    rule = manager._parse_rule(path)
    assert rule.fields[0].field_id == custom
