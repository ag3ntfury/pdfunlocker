import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("value", "expected"), [("MR", "Mr"), ("mr", "Mr"), ("Mrs", "Mrs"), ("MRS", "Mrs"), ("ms", "Ms"), ("miss", "Miss"), ("dr", "Dr"), ("OTHER", "Other"), (" Other ", "Other")])
def test_title_valid_choices_and_normalization(value, expected):
    assert validate_field_value("TITLE", value) == (expected, None)

@pytest.mark.parametrize("value", ["", "M", "SIR", "PROF", "MR.", "MR MRS", "1", "ＤＲ"])
def test_title_rejects_unknown_or_malformed_choices(value):
    if value == "":
        assert validate_field_value("TITLE", value) == ("", None)
    else:
        normalized, error = validate_field_value("TITLE", value)
        assert normalized is None and error

def test_title_single_value_and_profile_validation():
    assert validate_field_value("TITLE", "DR") == ("Dr", None)
