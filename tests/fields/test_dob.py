from datetime import date
import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["01011900", "01012000", "29022024", "31122000"])
def test_dob_accepts_valid_calendar_dates(value):
    if int(value[4:]) <= date.today().year:
        assert validate_field_value("DOB", value) == (value, None)

@pytest.mark.parametrize("value", ["29022023", "31042000", "00012000", "01132000", "01011899", "0101200", "010120000", "０１０１２０００", "01-01-2000"])
def test_dob_rejects_invalid_calendar_or_format(value):
    normalized, error = validate_field_value("DOB", value)
    assert normalized is None and error

def test_dob_rejects_future_year():
    value = f"0101{date.today().year + 1:04d}"
    normalized, error = validate_field_value("DOB", value)
    assert normalized is None and error

def test_dob_is_single_non_repeatable_field_contract():
    assert validate_field_value("DOB", "01012000")[1] is None
