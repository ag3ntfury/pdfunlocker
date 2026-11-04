import pytest

from pdfunlocker.profiles.validation import validate_field_value


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("ACCOUNT_NUMBER", "1234567890", "1234567890"),
        ("ACCOUNT_NUMBER_01", "1234 5678 90", "1234567890"),
        ("BANK_1200E_01", "GB29 NWBK 6016 1331", "GB29NWBK60161331"),
        ("BANK_1201E_02", "ab-1234", "AB1234"),
        ("BANK_1699E_01", "1234", "1234"),
        ("ACCOUNT_NUMBER_02", " ab-1234 ", "AB1234"),
    ],
)
def test_account_number_valid_values_and_normalization(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)


@pytest.mark.parametrize(
    "value",
    [
        "123",
        "A" * 35,
        "ABCD",
        "1234!567",
        "1234_567",
        "----",
        "１２３４",
        "ＡＢＣＤ１２３４",
        "ABＣD1234",
        "123４",
        "1234.567",
        "1234/567",
    ],
)
def test_account_number_rejects_invalid_values(value):
    normalized, error = validate_field_value("ACCOUNT_NUMBER_01", value)
    assert normalized is None and error


def test_account_number_empty_value_is_optional():
    assert validate_field_value("ACCOUNT_NUMBER", "") == ("", None)


def test_account_number_whitespace_only_value_is_optional():
    assert validate_field_value("ACCOUNT_NUMBER", "   ") == ("", None)
