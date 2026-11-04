from datetime import date
import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["15081947", "29022024", "0101" + str(date.today().year + 1)])
def test_incorporation_date_accepts_valid_past_and_future_dates(value):
    assert validate_field_value("INCORPORATION_DATE", value) == (value, None)

@pytest.mark.parametrize("value", ["31042000", "29022023", "00012000", "01132000", "01011899", "0101200", "０１０１２０００"])
def test_incorporation_date_rejects_invalid_calendar_or_format(value):
    normalized, error = validate_field_value("INCORPORATION_DATE", value)
    assert normalized is None and error
