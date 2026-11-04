from __future__ import annotations

from pdfunlocker.profiles import store
from pdfunlocker.profiles.registry import (
    FIELD_ID_BY_KEY,
    bank_field_id,
    bank_field_key,
    normalize_field_id,
)


def test_permanent_non_bank_field_ids_are_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
    for key, expected in FIELD_ID_BY_KEY.items():
        assert fields[key]["field_id"] == expected


def test_bank_group_ids_use_numeric_groups_and_letter_suffixes(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    first = store.ensure_bank_group(1200)
    second = store.ensure_bank_group(1201)
    assert [item["field_id"] for item in first] == [f"1200{x}" for x in "ABCDEF"]
    assert [item["field_id"] for item in second] == [f"1201{x}" for x in "ABCDEF"]
    assert bank_field_key(1202, "E") == "BANK_1202E"
    assert bank_field_id(1202, "F") == "1202F"


def test_bank_multiplicity_is_correct(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    store.ensure_bank_group(1200)
    fields = {item["field_id"]: item for item in store.list_fields()}
    assert fields["1200A"]["allows_multiple"] == 0
    for field_id in ("1200B", "1200C", "1200D", "1200E", "1200F"):
        assert fields[field_id]["allows_multiple"] == 1


def test_field_id_normalization_accepts_new_and_legacy_ids():
    assert normalize_field_id("0200") == "0200"
    assert normalize_field_id("1200e") == "1200E"
    assert normalize_field_id("001") == "001"
    assert normalize_field_id("1700") == "1700"
    assert normalize_field_id("9999Z") is None
