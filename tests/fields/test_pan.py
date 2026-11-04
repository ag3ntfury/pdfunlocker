import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("value", "expected"), [("ABCDE1234F", "ABCDE1234F"), ("abcde1234f", "ABCDE1234F"), (" Abcde1234f ", "ABCDE1234F")])
def test_pan_validates_and_normalizes_case_and_outer_whitespace(value, expected):
    assert validate_field_value("PAN", value) == (expected, None)

@pytest.mark.parametrize("value", ["ABCDE12345", "ABCD1234F", "ABCDE123F", "ABCDE1234", "12345ABCDE", "ABCDE-1234F", "ABCDE 1234F", "ＡＢＣＤＥ１２３４Ｆ"])
def test_pan_rejects_wrong_shape_or_non_ascii_characters(value):
    normalized, error = validate_field_value("PAN", value)
    assert normalized is None and error

def test_pan_single_value_and_profile_storage_validation():
    assert validate_field_value("PAN", "abcde1234f") == ("ABCDE1234F", None)
