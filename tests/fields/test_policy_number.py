import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("POLICY_NUMBER", "POL/2026-001", "POL/2026-001"), ("POLICY_NUMBER_01", " policy 123 ", "POLICY123"), ("POLICY_NUMBER_02", "AB.123", "AB.123")])
def test_policy_number_valid_values(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["_POL123", ".POL123", "POL_123", "POL@123", "A" * 129])
def test_policy_number_rejects_invalid_values(value):
    normalized, error = validate_field_value("POLICY_NUMBER", value)
    assert normalized is None and error
