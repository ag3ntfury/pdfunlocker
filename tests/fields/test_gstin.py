import pytest

from pdfunlocker.profiles.validation import validate_field_value


VALID_GSTIN = "27AAPFU0939F1ZV"  # Public format/checksum test vector.


def test_gstin_accepts_known_checksum_valid_value():
    assert validate_field_value("GSTIN", VALID_GSTIN) == (VALID_GSTIN, None)


def test_gstin_normalizes_lowercase():
    assert validate_field_value("GSTIN_01", VALID_GSTIN.lower()) == (
        VALID_GSTIN,
        None,
    )


@pytest.mark.parametrize(
    "value",
    [
        "27AAPFU0939F1ZW",
        "99AAPFU0939F1ZV",
        "27AAPFU0939F1XV",
        "27AAPFU0939F0ZV",
        "27AAAAA1234F1ZV",
        "2AAPFU0939F1ZV",
        "27AAPFU0939F1Z",
        "２７ＡＡＰＦＵ０９３９Ｆ１ＺＶ",
        "27 AAPFU0939F1ZV",
    ],
)
def test_gstin_rejects_invalid_structure_state_pan_entity_z_or_checksum(value):
    normalized, error = validate_field_value("GSTIN", value)
    assert normalized is None and error


@pytest.mark.parametrize(
    "value",
    [
        " " + VALID_GSTIN,
        VALID_GSTIN + " ",
        "  " + VALID_GSTIN + "  ",
    ],
)
def test_gstin_trims_surrounding_whitespace(value):
    assert validate_field_value("GSTIN", value) == (VALID_GSTIN, None)


def test_gstin_multiple_slots_are_independent():
    assert validate_field_value("GSTIN_01", VALID_GSTIN) == (
        VALID_GSTIN,
        None,
    )
    assert validate_field_value("GSTIN_02", VALID_GSTIN.lower()) == (
        VALID_GSTIN,
        None,
    )


def test_gstin_empty_value_is_optional():
    assert validate_field_value("GSTIN", "") == ("", None)
