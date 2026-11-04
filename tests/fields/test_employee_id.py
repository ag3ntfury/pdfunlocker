import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("EMPLOYEE_ID", "EMP-2026/001", "EMP-2026/001"), ("EMPLOYEE_ID_01", " emp. 123 ", "EMP.123"), ("EMPLOYEE_ID_02", "A123", "A123")])
def test_employee_id_valid_values(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["!ABC", "_ABC", "A" * 129, "ID_123"])
def test_employee_id_rejects_invalid_values(value):
    normalized, error = validate_field_value("EMPLOYEE_ID", value)
    assert normalized is None and error
