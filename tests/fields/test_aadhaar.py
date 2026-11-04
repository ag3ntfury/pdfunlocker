import pytest
from pdfunlocker.profiles.validation import validate_field_value, validate_profile_values

VALID_TEST_AADHAAR = "234567890124"  # Synthetic Verhoeff-valid test vector; not a real identity number.

def test_aadhaar_validates_checksum_and_returns_masked_value():
    masked, error = validate_field_value("AADHAAR", VALID_TEST_AADHAAR)
    assert error is None
    assert masked == "2345XXXX0124"
    assert VALID_TEST_AADHAAR not in masked

@pytest.mark.parametrize("value", ["23456789012", "2345678901245", "034567890124", "134567890124", "234567890125", "２３４５６７８９０１２４", "2345 6789 0124", "2345-6789-0124"])
def test_aadhaar_rejects_invalid_length_prefix_checksum_or_characters(value):
    normalized, error = validate_field_value("AADHAAR", value)
    assert normalized is None and error
    assert value not in (error or "")

def test_aadhaar_profile_storage_accepts_only_masked_representation():
    assert validate_profile_values({"AADHAAR": "2345XXXX0124"}) == []
    errors = validate_profile_values({"AADHAAR": VALID_TEST_AADHAAR})
    assert errors and any("normalization required" in item for item in errors)

def test_aadhaar_masked_value_shape_is_exact():
    for value in ["2345XXXX0124", "2345xxxx0124", "2345XXXX012", "2345XXXXX0124"]:
        errors = validate_profile_values({"AADHAAR": value})
        if value == "2345XXXX0124":
            assert errors == []
        else:
            assert errors
