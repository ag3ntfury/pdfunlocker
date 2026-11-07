import re

import pytest

from pdfunlocker.profiles.registry import (
    FIELD_ID_BY_KEY,
    GROUP_RANGES,
    bank_field_id,
    field_id_for_key,
    normalize_field_id,
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("TITLE", "1173"), ("FIRST_NAME", "1248"),
        ("MIDDLE_NAME", "1302"), ("LAST_NAME", "1371"),
        ("MOTHER_NAME", "1429"), ("DOB", "1506"),
        ("MOBILE", "1578"), ("EMAIL", "1641"), ("PINCODE", "1705"),
        ("PAN", "3197"), ("AADHAAR", "3268"),
        ("BANK_NAME", "4169"), ("IFSC", "4223"), ("CIF", "4298"),
        ("CUSTOMER_ID", "4356"), ("ACCOUNT_NUMBER", "4424"),
        ("CARD_NUMBER", "4487"), ("INCORPORATION_DATE", "6137"),
        ("TAN", "6194"), ("GSTIN", "6267"),
        ("EMPLOYEE_ID", "7141"), ("UAN", "7204"),
        ("PPO_NUMBER", "7276"), ("PRAN", "7331"),
        ("POLICY_NUMBER", "8173"), ("ROLL_NUMBER", "9178"),
    ],
)
def test_permanent_field_ids_are_stable(key, expected):
    assert FIELD_ID_BY_KEY[key] == expected
    assert normalize_field_id(expected) == expected


def test_group_ranges_are_exact():
    assert GROUP_RANGES == {
        "PERSONAL": (1001, 3000),
        "PRIVATE": (3001, 4000),
        "BANKING": (4001, 6000),
        "BUSINESS": (6001, 7000),
        "EMPLOYMENT": (7001, 8000),
        "INSURANCE": (8001, 9000),
        "EDUCATION": (9001, 10000),
    }


def test_builtin_ids_are_in_group_ranges_and_irregularly_spaced():
    group_keys = {
        "PERSONAL": ("TITLE", "FIRST_NAME", "MIDDLE_NAME", "LAST_NAME", "MOTHER_NAME", "DOB", "MOBILE", "EMAIL", "PINCODE", "BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR"),
        "PRIVATE": ("PAN", "AADHAAR", "AADHAAR_FIRST4", "AADHAAR_LAST4"),
        "BANKING": ("BANK_NAME", "IFSC", "CIF", "CUSTOMER_ID", "ACCOUNT_NUMBER", "CARD_NUMBER", "ACCOUNT_TITLE", "BRANCH", "ACCOUNT_TYPE"),
        "BUSINESS": ("INCORPORATION_DATE", "TAN", "GSTIN", "BUSINESS_NAME", "BUSINESS_REGISTRATION_NUMBER", "INCORPORATION_DAY", "INCORPORATION_MONTH", "INCORPORATION_YEAR"),
        "EMPLOYMENT": ("EMPLOYEE_ID", "UAN", "PPO_NUMBER", "PRAN"),
        "INSURANCE": ("POLICY_NUMBER", "INSURER_NAME", "POLICY_TYPE"),
        "EDUCATION": ("ROLL_NUMBER", "INSTITUTION_NAME", "QUALIFICATION", "COURSE", "ENROLLMENT_NUMBER", "REGISTRATION_NUMBER"),
    }
    for group, keys in group_keys.items():
        low, high = GROUP_RANGES[group]
        ids = sorted(int(FIELD_ID_BY_KEY[key]) for key in keys)
        assert all(low <= field_id <= high for field_id in ids)
        assert len(ids) == len(set(ids))
        assert all(41 <= right - left <= 80 for left, right in zip(ids, ids[1:]))


def test_bank_groups_share_field_type_ids():
    assert bank_field_id(1200, "A") == "4169"
    assert bank_field_id(1201, "A") == "4169"
    assert bank_field_id(1200, "E") == "4424"
    assert bank_field_id(1699, "E") == "4424"
    assert field_id_for_key("BANK_1200E", 1) == "4424"
    assert field_id_for_key("BANK_1699E", 999) == "4424"


def test_legacy_ids_resolve_to_new_permanent_ids():
    assert normalize_field_id("001") == "1248"
    assert normalize_field_id("009") == "1762"
    assert normalize_field_id("010") == "1829"
    assert normalize_field_id("011") == "1883"
    assert normalize_field_id("018") == "9178"
    assert normalize_field_id("021") == "4553"
    assert normalize_field_id("031") == "1173"
    assert normalize_field_id("0200") == "1248"
    assert normalize_field_id("1200E") == "4424"
    assert normalize_field_id("4424B") is None
    assert normalize_field_id("4424B", allow_value_instance=True) == "4424"
    assert normalize_field_id("999") is None
    assert normalize_field_id("2500") is None


def test_custom_category_is_not_an_available_category():
    from pdfunlocker.profiles.registry import normalize_field_category
    import pytest

    for category in (None, "", "Custom", "Other"):
        with pytest.raises(ValueError):
            normalize_field_category(category)
    assert normalize_field_category("Personal") == "Personal"
    assert normalize_field_category("Identity") == "Private"
