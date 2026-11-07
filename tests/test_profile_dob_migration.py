from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from pdfunlocker.profiles import manager, store
from pdfunlocker.profiles.validation import validate_field_value, validate_profile_values


def test_dob_accepts_valid_calendar_dates():
    assert validate_field_value("DOB", "01012000") == ("01012000", None)
    assert validate_field_value("DOB", "29022024") == ("29022024", None)


@pytest.mark.parametrize(
    "value",
    [
        "29022023",  # not a leap year
        "31042000",  # April has 30 days
        "00012000",
        "01132000",
        "01011900" if date.today().year < 1900 else "01011899",
        "0101",      # incomplete
        "010120000", # too long
        " 01012000", # leading whitespace
        "01012000 ", # trailing whitespace
        "０１０１２０００",  # non-ASCII digits
    ],
)
def test_dob_rejects_invalid_values(value):
    normalized, error = validate_field_value("DOB", value)
    assert normalized is None
    assert error


def test_dob_rejects_future_year():
    future = date.today().year + 1
    value = f"0101{future:04d}"
    normalized, error = validate_field_value("DOB", value)
    assert normalized is None
    assert error


def test_archived_legacy_fields_are_ignored_by_current_profile_validation():
    assert validate_profile_values(
        {
            "BIRTH_DAY": "not-a-day",
            "BIRTH_MONTH": "99",
            "BIRTH_YEAR": "old-value",
            "ACCOUNT_TITLE": "legacy account title",
        }
    ) == []


def test_fresh_registry_has_stable_dob_and_title_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    fields = {
        item["field_key"]: item
        for item in store.list_fields(include_archived=True)
    }

    assert fields["DOB"]["field_number"] == 9
    assert fields["DOB"]["archived"] == 0
    assert fields["TITLE"]["field_number"] == 31
    assert fields["BIRTH_DAY"]["field_number"] == 32
    assert fields["BIRTH_DAY"]["archived"] == 1
    assert fields["BIRTH_MONTH"]["archived"] == 1
    assert fields["BIRTH_YEAR"]["archived"] == 1
    assert fields["ACCOUNT_TITLE"]["archived"] == 1


def test_schema_v2_migration_preserves_values_and_builds_dob(tmp_path, monkeypatch):
    db_path = tmp_path / "profiles.sqlite3"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.initialize()

    now = "2026-11-03T00:00:00+00:00"
    with sqlite3.connect(db_path) as db:
        # Recreate the v2 registry arrangement: BIRTH_DAY owns ID 009,
        # and DOB/new-registry-only fields have not yet been introduced.
        db.execute("DELETE FROM field_definitions WHERE field_key IN ('AADHAAR','INCORPORATION_DATE','BANK_1200A','BANK_1200B','BANK_1200C','BANK_1200D','BANK_1200E','BANK_1200F')")
        db.execute("DELETE FROM field_definitions WHERE field_key='DOB'")
        db.execute(
            "UPDATE field_definitions SET field_number=-9 "
            "WHERE field_key='BIRTH_DAY'"
        )
        db.execute(
            "UPDATE field_definitions SET field_number=9 "
            "WHERE field_key='BIRTH_DAY'"
        )
        db.execute(
            "UPDATE field_definitions SET archived=0 "
            "WHERE field_key IN ('BIRTH_DAY','BIRTH_MONTH','BIRTH_YEAR','ACCOUNT_TITLE')"
        )
        db.execute(
            "INSERT INTO field_definitions"
            "(field_number,field_key,label,category,allows_multiple,archived,"
            "is_builtin,is_custom,created_at) "
            "VALUES((SELECT COALESCE(MAX(field_number),0)+1 FROM field_definitions),'LEGACY_CUSTOM','Legacy Custom','Custom',0,0,0,1,?)",
            (now,),
        )
        db.execute(
            "INSERT INTO profiles(profile_id,name,legacy_path,created_at,updated_at) "
            "VALUES(1,'Personal','profile01.env',?,?)",
            (now, now),
        )
        db.execute(
            "INSERT INTO profile_values"
            "(profile_id,field_key,value_sequence,value,created_at,updated_at) "
            "VALUES(1,?,?,?,?,?)",
            ("BIRTH_DAY", 0, "29", now, now),
        )
        db.execute(
            "INSERT INTO profile_values"
            "(profile_id,field_key,value_sequence,value,created_at,updated_at) "
            "VALUES(1,?,?,?,?,?)",
            ("BIRTH_MONTH", 0, "02", now, now),
        )
        db.execute(
            "INSERT INTO profile_values"
            "(profile_id,field_key,value_sequence,value,created_at,updated_at) "
            "VALUES(1,?,?,?,?,?)",
            ("BIRTH_YEAR", 0, "2000", now, now),
        )
        db.execute(
            "INSERT INTO profiles(profile_id,name,legacy_path,created_at,updated_at) "
            "VALUES(2,'Invalid Legacy','profile02.env',?,?)",
            (now, now),
        )
        for key, value in (
            ("BIRTH_DAY", "31"),
            ("BIRTH_MONTH", "04"),
            ("BIRTH_YEAR", "2000"),
        ):
            db.execute(
                "INSERT INTO profile_values"
                "(profile_id,field_key,value_sequence,value,created_at,updated_at) "
                "VALUES(2,?,?,?, ?, ?)",
                (key, 0, value, now, now),
            )
        db.execute(
            "UPDATE schema_metadata SET value='2' WHERE key='schema_version'"
        )

    store.initialize()

    profile_one = store.load_profile(1)
    profile_two = store.load_profile(2)
    assert profile_one is not None
    assert profile_two is not None
    assert profile_one["DOB"] == "29022000"
    assert profile_one["BIRTH_DAY"] == "29"
    assert profile_one["BIRTH_MONTH"] == "02"
    assert profile_one["BIRTH_YEAR"] == "2000"
    assert "DOB" not in profile_two
    assert profile_two["BIRTH_DAY"] == "31"

    fields = {
        item["field_key"]: item
        for item in store.list_fields(include_archived=True)
    }
    assert fields["DOB"]["field_number"] == 9
    assert fields["BIRTH_DAY"]["field_number"] != 9
    assert fields["BIRTH_DAY"]["archived"] == 1
    assert fields["BIRTH_MONTH"]["archived"] == 1
    assert fields["BIRTH_YEAR"]["archived"] == 1
    assert fields["ACCOUNT_TITLE"]["archived"] == 1
    assert fields["TITLE"]["field_number"] == 31
    assert fields["LEGACY_CUSTOM"]["field_number"] == 44


def test_personal_profile_fields_place_dob_after_names():
    personal = dict(manager.PROFILE_FIELDS)["Personal"]
    assert personal == (
        "TITLE",
        "FIRST_NAME",
        "LAST_NAME",
        "MIDDLE_NAME",
        "MOTHER_NAME",
        "DOB",
    )
    assert any(item[2] == "PINCODE" for item in manager.REPEATABLE_FIELDS)
    assert "BIRTH_DAY" not in personal
    assert "BIRTH_MONTH" not in personal
    assert "BIRTH_YEAR" not in personal
