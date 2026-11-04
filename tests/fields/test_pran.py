import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["123456789012", "000000000000", "999999999999"])
def test_pran_accepts_twelve_ascii_digits(value):
    assert validate_field_value("PRAN", value) == (value, None)

@pytest.mark.parametrize("value", ["12345678901", "1234567890123", "1234-5678-9012", "ABCDEFGHIJKL", "１２３４５６７８９０１２"])
def test_pran_rejects_invalid_values(value):
    normalized, error = validate_field_value("PRAN", value)
    assert normalized is None and error
