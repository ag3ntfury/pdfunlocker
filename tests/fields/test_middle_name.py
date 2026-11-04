import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["Keyal", "AB", "mIdDlE"])
def test_middle_name_valid(value):
    assert validate_field_value("MIDDLE_NAME", value) == (value, None)

@pytest.mark.parametrize("value", ["K", "K.", "Middle Name", "A-Name", "Name1", "Émile"])
def test_middle_name_invalid(value):
    normalized, error = validate_field_value("MIDDLE_NAME", value)
    assert normalized is None and error
