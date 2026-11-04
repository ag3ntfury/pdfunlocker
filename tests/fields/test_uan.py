import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["123456789012", "000000000000", "999999999999"])
def test_uan_accepts_exactly_twelve_ascii_digits(value):
    assert validate_field_value("UAN", value) == (value, None)

@pytest.mark.parametrize("value", ["12345678901", "1234567890123", "1234 6789 012", "ABCDEFGHIJKL", "１２３４５６７８９０１２"])
def test_uan_rejects_wrong_length_or_non_ascii_digits(value):
    normalized, error = validate_field_value("UAN", value)
    assert normalized is None and error

def test_uan_repeatable_suffix():
    assert validate_field_value("UAN_02", "123456789012") == ("123456789012", None)
