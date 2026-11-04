import pytest
from pdfunlocker.profiles.validation import validate_field_value, validate_profile_values

@pytest.mark.parametrize("field", [None, 1, [], {}])
def test_non_text_field_names_are_rejected(field):
    normalized, error = validate_field_value(field, "abc")
    assert normalized is None and error

def test_non_text_values_are_rejected():
    for value in [None, 1, [], {}]:
        normalized, error = validate_field_value("FIRST_NAME", value)
        assert normalized is None and error

def test_empty_optional_values_are_accepted_for_each_field_family():
    for field in ["TITLE", "FIRST_NAME", "DOB", "MOBILE_01", "EMAIL_01", "PINCODE_01", "PAN", "AADHAAR", "IFSC_01", "GSTIN_01", "TAN_01"]:
        assert validate_field_value(field, "") == ("", None)

def test_profile_validation_rejects_unnormalized_values():
    errors = validate_profile_values({"PAN": "abcde1234f", "MOBILE_01": "9876543210", "PINCODE_01": " 361305 "})
    assert len(errors) == 3
    assert {item.split(":", 1)[0] for item in errors} == {"PAN", "MOBILE_01", "PINCODE_01"}
