import pytest
from pdfunlocker.profiles.registry import FIELD_ID_BY_KEY, bank_field_id, field_id_for_key, normalize_field_id

@pytest.mark.parametrize(("key", "expected"), [("TITLE", "0100"), ("FIRST_NAME", "0200"), ("LAST_NAME", "0300"), ("MIDDLE_NAME", "0400"), ("MOTHER_NAME", "0500"), ("DOB", "0600"), ("MOBILE", "0700"), ("EMAIL", "0800"), ("PINCODE", "0900"), ("PAN", "1000"), ("AADHAAR", "1100"), ("INCORPORATION_DATE", "1700"), ("TAN", "1800"), ("GSTIN", "1900"), ("EMPLOYEE_ID", "2000"), ("UAN", "2100"), ("PPO_NUMBER", "2200"), ("PRAN", "2300"), ("POLICY_NUMBER", "2400")])
def test_permanent_field_ids_are_stable(key, expected):
    assert FIELD_ID_BY_KEY[key] == expected
    assert normalize_field_id(expected) == expected

def test_bank_ids_are_stable_for_first_and_last_groups():
    assert bank_field_id(1200, "A") == "1200A"
    assert bank_field_id(1200, "F") == "1200F"
    assert bank_field_id(1699, "E") == "1699E"

def test_legacy_ids_remain_normalizable_without_reuse():
    assert normalize_field_id("001") == "001"
    assert normalize_field_id("031") == "031"
    assert normalize_field_id("999") == "999"
    assert normalize_field_id("0100") == "0100"
    assert normalize_field_id("1200A") == "1200A"
    assert normalize_field_id("1700") == "1700"
    assert normalize_field_id("2500") is None
