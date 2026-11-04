import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("TAN", "MUMA12345B", "MUMA12345B"), ("TAN", "muma12345b", "MUMA12345B"), ("TAN_01", "ABCD00001Z", "ABCD00001Z")])
def test_tan_validates_and_normalizes(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["MUMA1234B", "MUMA123456B", "123A12345B", "MUMA12345", "MUMA1234!B", "ＭＵＭＡ１２３４５Ｂ"])
def test_tan_rejects_invalid_shape(value):
    normalized, error = validate_field_value("TAN", value)
    assert normalized is None and error
