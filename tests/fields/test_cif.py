import pytest

from pdfunlocker.profiles.validation import validate_field_value


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("CIF", "123456789", "123456789"),
        ("CIF_01", "ab/123-xy", "AB/123-XY"),
        ("BANK_1200C_01", "  cif 2026 ", "CIF2026"),
        ("BANK_1201C_02", "ABC.123", "ABC.123"),
    ],
)
def test_cif_accepts_supported_identifier_characters_and_normalizes(
    field, value, expected
):
    assert validate_field_value(field, value) == (expected, None)


@pytest.mark.parametrize(
    "value",
    [
        "-ABC",
        ".ABC",
        "ABC_123",
        "ABC@123",
        "A" * 129,
        "１２３４",
    ],
)
def test_cif_rejects_invalid_identifiers(value):
    normalized, error = validate_field_value("CIF", value)
    assert normalized is None and error


@pytest.mark.parametrize("value", ["", " ", "   ", "\t", "\n"])
def test_cif_empty_or_whitespace_only_value_is_optional(value):
    assert validate_field_value("CIF", value) == ("", None)


def test_cif_multiple_slots_are_independent():
    assert validate_field_value("BANK_1200C_01", "CIF001") == ("CIF001", None)
    assert validate_field_value("BANK_1200C_02", "CIF002") == ("CIF002", None)
