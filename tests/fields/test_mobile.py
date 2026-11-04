import pytest

from pdfunlocker.profiles.validation import (
    normalize_country_calling_code,
    validate_field_value,
)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("MOBILE", "9876543210", "+919876543210"),
        ("MOBILE_01", "9876543210", "+919876543210"),
        ("MOBILE_02", "+919876543210", "+919876543210"),
        ("MOBILE_03", "00447911123456", "+447911123456"),
        ("MOBILE_04", "+447911123456", "+447911123456"),
        ("MOBILE_05", "919876543210", "+919876543210"),
        ("MOBILE_06", "+91 98765 43210", "+919876543210"),
        ("MOBILE_07", "+91-98765-43210", "+919876543210"),
        ("MOBILE_08", "(98765) 43210", "+919876543210"),
        ("MOBILE_09", "+91 (98765) 43210", "+919876543210"),
    ],
)
def test_mobile_valid_values_normalize_to_e164(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)


@pytest.mark.parametrize(
    "value",
    [
        "123",
        "1234567890",
        "abcdefghij",
        "+999123456789",
        "+911234567890",
        "98765-43210x",
        "98765-43210 ext 2",
        "++919876543210",
        "+91+9876543210",
        "91+9876543210",
        "+91 98765 43210+",
        "９８７６５４３２１０",
        "98765(43210",
        "98765)43210(",
    ],
)
def test_mobile_rejects_invalid_values(value):
    normalized, error = validate_field_value("MOBILE", value)
    assert normalized is None and error


def test_mobile_empty_value_is_optional():
    assert validate_field_value("MOBILE", "") == ("", None)


def test_mobile_whitespace_only_value_is_optional():
    assert validate_field_value("MOBILE", "   ") == ("", None)


def test_country_calling_code_validation():
    assert normalize_country_calling_code("") == "+91"
    assert normalize_country_calling_code("91") == "+91"
    assert normalize_country_calling_code("+44") == "+44"
    assert normalize_country_calling_code("999") is None
    assert normalize_country_calling_code("+91x") is None
    assert normalize_country_calling_code("９１") is None
