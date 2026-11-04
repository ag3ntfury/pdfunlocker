import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["Rupesh", "RAHUL", "john", "Ab", "ABCDEFGHIJKLMNOPQRSTUVWXYZ"])
def test_first_name_accepts_two_or_more_ascii_letters(value):
    assert validate_field_value("FIRST_NAME", value) == (value, None)

@pytest.mark.parametrize("value", ["", "R", "R.", "John Doe", "Anne-Marie", "O'Neil", "José", "John2", " John", "John ", "A_B", "１２"])
def test_first_name_rejects_non_contract_values(value):
    if value == "":
        assert validate_field_value("FIRST_NAME", value) == ("", None)
    else:
        normalized, error = validate_field_value("FIRST_NAME", value)
        assert normalized is None and error

def test_first_name_repeatable_suffix_uses_same_validator():
    assert validate_field_value("FIRST_NAME_02", "Rahul") == ("Rahul", None)
