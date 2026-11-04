import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["Bhadarka", "Gohel", "Smith", "Li", "OBrien"])
def test_last_name_valid(value):
    assert validate_field_value("LAST_NAME", value) == (value, None)

@pytest.mark.parametrize("value", ["B", "Bhadarka Patel", "Bhadarka-Patel", "O'Neil", "Patel.", "Patel123", " Patel"])
def test_last_name_invalid(value):
    normalized, error = validate_field_value("LAST_NAME", value)
    assert normalized is None and error
