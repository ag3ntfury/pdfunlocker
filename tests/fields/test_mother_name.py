import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["Rekha", "Rekha Ben", "Rekha Bhadarka", "Mary Jane Watson", "AB CD"])
def test_mother_name_accepts_single_or_multiple_words(value):
    assert validate_field_value("MOTHER_NAME", value) == (value, None)

@pytest.mark.parametrize("value", ["R", "R.", "Rekha  Ben", " Rekha", "Rekha ", "Rekha-Ben", "Rekha123", "Rekha_Ben", "José Doe", "Rekha\tBen"])
def test_mother_name_rejects_invalid_word_separators_and_characters(value):
    normalized, error = validate_field_value("MOTHER_NAME", value)
    assert normalized is None and error
