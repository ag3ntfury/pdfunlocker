import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("PINCODE", "361305", "361305"), ("PINCODE_01", "361305", "361305"), ("PINCODE_02", " 361305 ", "361305"), ("PINCODE_03", "GB:SW1A 1AA", "GB:SW1A 1AA"), ("PINCODE_04", "us:90210", "US:90210"), ("PINCODE_05", "CA:K1A 0B1", "CA:K1A 0B1")])
def test_pincode_valid_indian_and_explicit_international_values(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["1", "12345", "1234567", "012345", "000000", "90210", "GB", "GB:", "XX:12345", "US:0", "US:00000", "US:ABCDE!", "361 305", "３６１３０５"])
def test_pincode_rejects_invalid_or_ambiguous_values(value):
    normalized, error = validate_field_value("PINCODE", value)
    assert normalized is None and error

def test_pincode_repeatable_slots_are_independent():
    assert validate_field_value("PINCODE_01", "361305") == ("361305", None)
    assert validate_field_value("PINCODE_02", "GB:SW1A 1AA") == ("GB:SW1A 1AA", None)
