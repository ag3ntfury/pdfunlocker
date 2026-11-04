import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("CARD_NO", "4111111111111111", "4111111111111111"), ("CARD_NO_01", "4111 1111 1111 1111", "4111111111111111"), ("BANK_1200F_01", "4111-1111-1111-1111", "4111111111111111"), ("BANK_1201F_02", "378282246310005", "378282246310005"), ("CARD_NO", "6011111111111117", "6011111111111117")])
def test_card_number_accepts_luhn_valid_full_number_for_encrypted_persistence(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["4111111111111112", "1234", "411111111111", "41111111111111111111", "4111 1111 1111 111X", "４１１１１１１１１１１１１１１１"])
def test_card_number_rejects_invalid_length_or_luhn(value):
    normalized, error = validate_field_value("CARD_NO", value)
    assert normalized is None and error

def test_card_number_does_not_return_masked_value_at_input_validation_stage():
    normalized, error = validate_field_value("CARD_NO", "4111111111111111")
    assert error is None and normalized == "4111111111111111"
