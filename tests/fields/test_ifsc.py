import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("IFSC", "SBIN0001234", "SBIN0001234"), ("IFSC_01", "sbin0001234", "SBIN0001234"), ("BANK_1200B_01", "hdfc0001234", "HDFC0001234"), ("BANK_1201B_02", "icic0000456", "ICIC0000456")])
def test_ifsc_valid_format_and_case_normalization(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["SBIN1234567", "SBIN000123", "SBI00012345", "12340001234", "SBIN00012!4", "ＳＢＩＮ０００１２３４"])
def test_ifsc_rejects_invalid_format(value):
    normalized, error = validate_field_value("IFSC_01", value)
    assert normalized is None and error
