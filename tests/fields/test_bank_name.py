import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("BANK_NAME", "State Bank of India", "State Bank of India"), ("BANK_NAME", " State   Bank  of India ", "State Bank of India"), ("BANK_1200A", "Bank of Baroda", "Bank of Baroda"), ("BANK_1201A", "HDFC Bank", "HDFC Bank")])
def test_bank_name_normalizes_whitespace(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

def test_bank_name_accepts_maximum_length():
    value = "A" * 100
    assert validate_field_value("BANK_1200A", value) == (value, None)

def test_bank_name_rejects_overlong_and_control_characters():
    for value in ["A" * 101, "Bank\x00Name", "Bank\x01Name"]:
        normalized, error = validate_field_value("BANK_1200A", value)
        assert normalized is None and error
