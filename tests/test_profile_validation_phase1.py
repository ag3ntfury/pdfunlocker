from __future__ import annotations

from datetime import date

import pytest

phonenumbers = pytest.importorskip("phonenumbers")

from pdfunlocker.profiles.validation import (  # noqa: E402
    VALID_COUNTRY_CALLING_CODES,
    normalize_country_calling_code,
    validate_field_value,
    validate_profile_values,
)


# Synthetic Verhoeff-valid test number; it is not a real Aadhaar number.
VALID_TEST_AADHAAR = "234567890124"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("DOB", "01012000", "01012000"),
        ("DOB", "29022024", "29022024"),
        ("INCORPORATION_DATE", "15081947", "15081947"),
        ("INCORPORATION_DATE", "29022024", "29022024"),
        ("PINCODE", "361305", "361305"),
        ("PINCODE_01", "361305", "361305"),
        ("PINCODE_02", "GB:SW1A 1AA", "GB:SW1A 1AA"),
        ("PINCODE_03", "US:90210", "US:90210"),
        ("CARD_NO", "4111 1111 1111 1111", "4111111111111111"),
        ("CREDIT_CARD_NUMBER_01", "4111-1111-1111-1111", "4111111111111111"),
        ("BANK_NAME", "State Bank of India", "State Bank of India"),
        ("BANK_NAME", "State   Bank  of India", "State Bank of India"),
        ("IFSC_01", "SBIN0001234", "SBIN0001234"),
        ("CIF_01", "123456789", "123456789"),
        ("CUSTOMER_ID_01", "ABC12345", "ABC12345"),
    ],
)
def test_valid_profile_values(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DOB", "29022023"),
        ("DOB", "31042000"),
        ("DOB", "00012000"),
        ("DOB", "01132000"),
        ("DOB", "01011900" if date.today().year < 1900 else "01011899"),
        ("DOB", "010120000"),
        ("DOB", "０１０１２０００"),
        ("INCORPORATION_DATE", "31042000"),
        ("PINCODE_01", "1"),
        ("PINCODE_02", "INVALID!"),
        ("CARD_NO", "4111111111111112"),
        ("CARD_NO", "1234"),
    ],
)
def test_invalid_profile_values(field, value):
    normalized, error = validate_field_value(field, value)
    assert normalized is None
    assert error


def test_dob_rejects_future_year():
    future = date.today().year + 1
    normalized, error = validate_field_value("DOB", f"0101{future:04d}")
    assert normalized is None
    assert error


def test_incorporation_date_accepts_a_valid_future_calendar_date():
    future = date.today().year + 1
    value = f"0101{future:04d}"
    assert validate_field_value("INCORPORATION_DATE", value) == (value, None)


def test_aadhaar_validates_verhoeff_and_returns_only_masked_value():
    normalized, error = validate_field_value("AADHAAR", VALID_TEST_AADHAAR)
    assert error is None
    assert normalized == "2345XXXX0124"
    assert VALID_TEST_AADHAAR not in normalized


@pytest.mark.parametrize(
    "value",
    [
        "23456789012",       # 11 digits
        "2345678901245",     # 13 digits
        "034567890124",      # starts with 0
        "134567890124",      # starts with 1
        "234567890125",      # checksum changed
        "２３４５６７８９０１２４",  # non-ASCII digits
        "2345 6789 0124",    # spaces are not accepted
    ],
)
def test_aadhaar_rejects_invalid_input(value):
    normalized, error = validate_field_value("AADHAAR", value)
    assert normalized is None
    assert error
    assert value not in error


def test_aadhaar_profile_validation_accepts_masked_storage_value():
    assert validate_profile_values({"AADHAAR": "2345XXXX0124"}) == []


def test_aadhaar_profile_validation_rejects_unmasked_persisted_value():
    errors = validate_profile_values({"AADHAAR": VALID_TEST_AADHAAR})
    assert errors
    assert any("normalization required" in error for error in errors)


def test_aadhaar_profile_validation_ignores_archived_components():
    # Archived fields remain ignored. Legacy split DOB is deliberately tested
    # separately because the existing project contract validates it when all
    # three components are present, while incomplete legacy DOB is ignored.
    assert validate_profile_values(
        {
            "AADHAAR_FIRST4": "bad",
            "AADHAAR_LAST4": "legacy",
            "INCORPORATION_DAY": "bad",
            "INCORPORATION_MONTH": "99",
            "INCORPORATION_YEAR": "legacy",
            "ACCOUNT_TITLE": "legacy",
            "ROLL_NUMBER": "legacy",
        }
    ) == []


def test_mobile_defaults_to_india_and_uses_e164():
    assert validate_field_value("MOBILE_01", "9876543210") == (
        "+919876543210",
        None,
    )


def test_mobile_preserves_explicit_international_prefix():
    assert validate_field_value("MOBILE_01", "+447911123456") == (
        "+447911123456",
        None,
    )


def test_mobile_accepts_00_international_prefix():
    assert validate_field_value("MOBILE_01", "00447911123456") == (
        "+447911123456",
        None,
    )


def test_mobile_rejects_invalid_number():
    normalized, error = validate_field_value("MOBILE_01", "123")
    assert normalized is None
    assert error


def test_country_calling_codes_come_from_library_metadata():
    assert "91" in VALID_COUNTRY_CALLING_CODES
    assert normalize_country_calling_code("") == "+91"
    assert normalize_country_calling_code("+44") == "+44"
    assert normalize_country_calling_code("999") is None


def test_email_multiple_value_keys_are_validated_independently():
    assert validate_field_value("EMAIL_01", "one@example.com") == (
        "one@example.com",
        None,
    )
    assert validate_field_value("EMAIL_02", "two@example.org") == (
        "two@example.org",
        None,
    )


def test_card_no_and_legacy_card_key_are_both_validated():
    assert validate_field_value("CARD_NO_01", "4111111111111111") == (
        "4111111111111111",
        None,
    )
    assert validate_field_value(
        "CREDIT_CARD_NUMBER_01", "4111111111111111"
    ) == ("4111111111111111", None)


def test_profile_validation_requires_normalized_mobile_values():
    errors = validate_profile_values({"MOBILE_01": "9876543210"})
    assert errors
    assert any("normalization required" in error for error in errors)


def test_profile_validation_accepts_normalized_values_and_masked_aadhaar():
    errors = validate_profile_values(
        {
            "DOB": "01012000",
            "INCORPORATION_DATE": "15081947",
            "MOBILE_01": "+919876543210",
            "EMAIL_01": "one@example.com",
            "PINCODE_01": "361305",
            "AADHAAR": "2345XXXX0124",
            "CARD_NO_01": "XXXXXXXXXXXX1111",
        }
    )
    assert errors == []


def test_name_validation_remains_strict():
    assert validate_field_value("FIRST_NAME", "Rupesh") == ("Rupesh", None)
    assert validate_field_value("FIRST_NAME", "Rupesh Kumar")[0] is None
    assert validate_field_value("FIRST_NAME", "R.") [0] is None
    assert validate_field_value("MOTHER_NAME", "Rita Ben")[0] == "Rita Ben"


def test_bank_group_fields_use_their_specific_validators():
    assert validate_field_value("BANK_1200A", "State   Bank of India") == (
        "State Bank of India", None
    )
    assert validate_field_value("BANK_1200B_01", "sbin0001234") == (
        "SBIN0001234", None
    )
    assert validate_field_value("BANK_1200E_01", "1234567890") == (
        "1234567890", None
    )


def test_bank_card_number_is_returned_full_for_encrypted_persistence():
    assert validate_field_value("BANK_1200F_01", "4111111111111111") == (
        "4111111111111111", None
    )
