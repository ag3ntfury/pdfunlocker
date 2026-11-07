import pytest
from pdfunlocker.profiles.validation import validate_field_value
from pdfunlocker.profiles.registry import bank_field_id, bank_field_key

@pytest.mark.parametrize("group", [1200, 1201, 1250, 1699])
def test_each_bank_group_exposes_six_stable_field_ids(group):
    assert [bank_field_id(group, suffix) for suffix in "ABCDEF"] == ["4169", "4223", "4298", "4356", "4424", "4487"]
    assert [bank_field_key(group, suffix) for suffix in "ABCDEF"] == [f"BANK_{group}{suffix}" for suffix in "ABCDEF"]

@pytest.mark.parametrize(("field", "value", "expected"), [("BANK_1200A", "State   Bank of India", "State Bank of India"), ("BANK_1200B_01", "sbin0001234", "SBIN0001234"), ("BANK_1200C_01", "cif 123", "CIF123"), ("BANK_1200D_01", "cust 123", "CUST123"), ("BANK_1200E_01", "1234 5678", "12345678"), ("BANK_1200F_01", "4111 1111 1111 1111", "4111111111111111"), ("BANK_1201B_02", "hdfc0001234", "HDFC0001234"), ("BANK_1699E_03", "AB-1234", "AB1234")])
def test_bank_slots_route_to_the_correct_field_validator(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

def test_bank_group_bounds_and_suffix_are_enforced_by_registry_helpers():
    with pytest.raises(ValueError):
        bank_field_key(1199, "A")
    with pytest.raises(ValueError):
        bank_field_key(1700, "A")
    with pytest.raises(ValueError):
        bank_field_key(1200, "G")

def test_bank_fields_validate_and_account_numbers_support_multiple_values():
    assert validate_field_value("BANK_1200A", "Bank of Baroda")[1] is None
    for key, value in [("BANK_1200B", "SBIN0001234"), ("BANK_1200C", "CIF001"), ("BANK_1200D", "CUST001"), ("BANK_1200E_01", "12345678"), ("BANK_1200E_02", "87654321")]:
        assert validate_field_value(key, value)[1] is None
