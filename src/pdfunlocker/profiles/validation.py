"""Reusable, non-interactive validation and normalization for profile values.

This module has no CLI prompts, database access, or profile-storage side effects.
Personal Mode and future Enterprise Mode should use these public functions.
"""
from __future__ import annotations

import re
from datetime import date

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, PhoneNumberType

__all__ = [
    "VALID_COUNTRY_CALLING_CODES",
    "normalize_country_calling_code",
    "validate_field_value",
    "validate_profile_values",
]

# Derive supported calling codes from libphonenumber metadata. This avoids
# maintaining a second, potentially stale country-code list in PDF Unlocker.
VALID_COUNTRY_CALLING_CODES = frozenset(
    str(code) for code in phonenumbers.COUNTRY_CODE_TO_REGION_CODE
)


# GSTIN state/UT jurisdiction codes, including 97 = Other Territory.
VALID_GST_STATE_CODES = frozenset({
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
    "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
    "21", "22", "23", "24", "25", "26", "27", "28", "29", "30",
    "31", "32", "33", "34", "35", "36", "37", "38", "97",
})

_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def normalize_country_calling_code(value: str) -> str | None:
    """Normalize and validate an international country calling code."""
    value = value.strip()
    if not value:
        return "+91"
    if not re.fullmatch(r"\+?[0-9]{1,3}", value):
        return None
    digits = value.removeprefix("+")
    return f"+{digits}" if digits in VALID_COUNTRY_CALLING_CODES else None


def _luhn_valid(number: str) -> bool:
    total = 0
    for index, char in enumerate(number[::-1]):
        digit = int(char)
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _mask_card(number: str) -> str:
    """Persist only the final four card digits; never retain the full PAN."""
    return ("X" * (len(number) - 4)) + number[-4:]


def _valid_masked_card(value: str) -> bool:
    return bool(re.fullmatch(r"X{8,15}[0-9]{4}", value))


# Verhoeff checksum tables used for Aadhaar input validation.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _verhoeff_valid(number: str) -> bool:
    """Return whether an ASCII digit string has a valid Verhoeff checksum."""
    checksum = 0
    for index, digit in enumerate(reversed(number)):
        checksum = _VERHOEFF_D[checksum][
            _VERHOEFF_P[index % 8][int(digit)]
        ]
    return checksum == 0


def _mask_aadhaar(number: str) -> str:
    """Return the only Aadhaar representation permitted in profile storage."""
    return f"{number[:4]}XXXX{number[-4:]}"


def _valid_masked_aadhaar(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9]{4}XXXX[0-9]{4}", value))


def _validate_date_ddmmyyyy(
    value: str, field_label: str, *, allow_future: bool = False
) -> tuple[str | None, str | None]:
    if not re.fullmatch(r"[0-9]{8}", value):
        return None, f"{field_label} must contain exactly 8 ASCII digits in DDMMYYYY format."

    day = int(value[:2])
    month = int(value[2:4])
    year = int(value[4:])
    current_year = date.today().year
    if year < 1900 or (not allow_future and year > current_year):
        upper = "9999" if allow_future else str(current_year)
        return None, f"{field_label} year must be between 1900 and {upper}."

    try:
        date(year, month, day)
    except ValueError:
        return None, f"{field_label} must be a valid calendar date in DDMMYYYY format."

    return value, None


def _normalize_mobile(value: str) -> str | None:
    """Validate a country-specific mobile number and return E.164 format."""
    candidate = value.strip()
    if not candidate:
        return None

    # Accept ASCII digits and conventional visual separators only.
    # Reject letters, extensions, Unicode digits, and unsupported symbols.
    if not re.fullmatch(r"[0-9+().\-\s]+", candidate):
        return None

    # A plus sign is permitted only once, at the beginning.
    if candidate.count("+") > 1:
        return None
    if "+" in candidate and not candidate.startswith("+"):
        return None

    # Reject unmatched or incorrectly ordered parentheses.
    depth = 0
    for char in candidate:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return None
    if depth != 0:
        return None

    if candidate.startswith("00"):
        candidate = "+" + candidate[2:]

    # Bare Indian national numbers use India's numbering plan.
    region = None if candidate.startswith("+") else "IN"

    try:
        number = phonenumbers.parse(candidate, region)
    except NumberParseException:
        return None

    if not phonenumbers.is_possible_number(number):
        return None
    if not phonenumbers.is_valid_number(number):
        return None

    number_type = phonenumbers.number_type(number)
    if number_type not in {
        PhoneNumberType.MOBILE,
        PhoneNumberType.FIXED_LINE_OR_MOBILE,
    }:
        return None

    return phonenumbers.format_number(number, PhoneNumberFormat.E164)

def _gstin_checksum(first_fourteen: str) -> str:
    """Return the GSTIN mod-36 Luhn-style check character."""
    total = 0
    for index, char in enumerate(first_fourteen):
        product = _GSTIN_CHARS.index(char) * (1 if index % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def _valid_gstin(value: str) -> bool:
    if not re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value):
        return False

    if value[:2] not in VALID_GST_STATE_CODES:
        return False

    # Positions 3-12 contain the embedded PAN.
    pan = value[2:12]
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
        return False

    # Position 13 is the entity number; position 14 must be literal Z.
    if value[12] == "0" or value[13] != "Z":
        return False

    return value[14] == _gstin_checksum(value[:14])


def _validate_email(value: str) -> tuple[str | None, str | None]:
    """Validate standard email syntax while preserving the original value."""
    if value != value.strip() or any(char.isspace() for char in value):
        return None, "Email addresses cannot contain whitespace."

    if value.count("@") != 1:
        return None, "Enter a valid email address."

    local, domain = value.rsplit("@", 1)

    local_pattern = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"

    if (
        not local
        or len(local) > 64
        or not re.fullmatch(local_pattern, local)
        or not domain
        or "." not in domain
    ):
        return None, "Enter a valid email address."

    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        return None, "Invalid email domain."

    labels = ascii_domain.split(".")
    if (
        len(ascii_domain) > 253
        or len(labels[-1]) < 2
        or any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[A-Za-z0-9-]+", label)
            for label in labels
        )
    ):
        return None, "Invalid email domain."

    return value, None


def _validate_and_normalize(
    field: str, value: str, *, allow_masked_aadhaar: bool = False
) -> tuple[str | None, str | None]:
    """Pure profile-field validation. Returns (normalized_value, error)."""
    if not isinstance(field, str) or not isinstance(value, str):
        return None, "Field name and value must be text."

    # Numeric suffixes identify repeatable values (for example, PINCODE_01).
    # Validation uses the base key; persistence keeps the original key.
    # Numeric suffixes identify repeatable values (for example, PINCODE_01).
    # Validation uses the base key; persistence keeps the original key.
    base = re.sub(r"_\d+$", "", field).upper()
    bank_match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})([A-F])", base)
    if bank_match:
        base = {
            "A": "BANK_NAME", "B": "IFSC", "C": "CIF",
            "D": "CUSTOMER_ID", "E": "ACCOUNT_NUMBER", "F": "CARD_NO",
        }[bank_match.group(2)]

    if value == "":
        return "", None

    if base == "CARD_NO":
        from pdfunlocker.profiles.card_crypto import is_encrypted_card
        if is_encrypted_card(value):
            return value, None

    # These fields must not be silently trimmed or case-normalized.
    if base == "EMAIL":
        return _validate_email(value)

    if base in {"FIRST_NAME", "MIDDLE_NAME", "LAST_NAME"}:
        if not re.fullmatch(r"[A-Za-z]{2,}", value):
            return None, (
                f"{base} must contain at least 2 English letters only. "
                "Initials, spaces, periods, hyphens, and special characters are not allowed."
            )
        return value, None

    if base == "MOTHER_NAME":
        if not re.fullmatch(r"[A-Za-z]{2,}(?: [A-Za-z]{2,})*", value):
            return None, (
                "MOTHER_NAME must contain English name words only, "
                "separated by single spaces."
            )
        return value, None

    if base == "AADHAAR":
        if allow_masked_aadhaar and _valid_masked_aadhaar(value):
            return value, None
        if not re.fullmatch(r"[0-9]{12}", value):
            return None, "AADHAAR must contain exactly 12 ASCII digits."
        if value[0] in {"0", "1"}:
            return None, "AADHAAR must not start with 0 or 1."
        if not _verhoeff_valid(value):
            return None, "AADHAAR failed the Verhoeff checksum."
        return _mask_aadhaar(value), None

    if base == "DOB":
        return _validate_date_ddmmyyyy(value, "DOB")

    if base == "INCORPORATION_DATE":
        return _validate_date_ddmmyyyy(value, "INCORPORATION_DATE", allow_future=True)

    value = value.strip()
    if not value:
        return "", None

    if base == "TITLE":
        normalized = value.upper()
        if normalized not in {"MR", "MRS", "MS", "MISS", "DR", "OTHER"}:
            return None, "Choose one of: Mr, Mrs, Ms, Miss, Dr, Other."
        return ("Dr" if normalized == "DR" else normalized.title()), None

    if base == "BANK_NAME":
        normalized = re.sub(r"\s+", " ", value).strip()
        if not normalized or len(normalized) > 100:
            return None, "BANK_NAME must contain 1 to 100 characters."
        if any(ord(char) < 32 for char in normalized):
            return None, "BANK_NAME contains unsupported control characters."
        return normalized, None

    if base == "PAN":
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", normalized):
            return None, "PAN must use the format ABCDE1234F."
        return normalized, None

    if base == "IFSC":
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", normalized):
            return None, "IFSC must contain 4 letters, 0, and 6 letters or digits."
        return normalized, None

    if base == "GSTIN":
        normalized = value.upper()
        if not _valid_gstin(normalized):
            return None, (
                "GSTIN is invalid: check its structure, state code, embedded "
                "PAN, entity code, Z character, and checksum."
            )
        return normalized, None

    if base == "TAN":
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{4}[0-9]{5}[A-Z]", normalized):
            return None, "TAN must contain 4 letters, 5 digits, and 1 letter."
        return normalized, None

    if base in {"UAN", "PRAN"}:
        if not re.fullmatch(r"[0-9]{12}", value):
            return None, f"{base} must contain exactly 12 digits."
        return value, None

    if base == "PINCODE":
        normalized = re.sub(r"\s+", " ", value).strip().upper()
        # India is the default: six digits, first digit 1-9.
        if re.fullmatch(r"[1-9][0-9]{5}", normalized):
            return normalized, None
        # International addresses must be explicit: CC:POSTAL, e.g. US:90210.
        match = re.fullmatch(r"([A-Z]{2}):([A-Z0-9][A-Z0-9 -]{0,10}[A-Z0-9])", normalized)
        if match:
            country, postal = match.groups()
            try:
                import phonenumbers
                supported = country in phonenumbers.SUPPORTED_REGIONS
            except Exception:
                supported = country in {"US", "CA", "GB", "AU", "NZ", "DE", "FR", "JP", "SG", "AE"}
            compact = postal.replace(" ", "").replace("-", "")
            if supported and 2 <= len(compact) <= 12 and not re.fullmatch(r"0+", compact):
                return f"{country}:{postal}", None
        return None, (
            "Enter a valid 6-digit Indian PIN code, or use COUNTRY:POSTAL "
            "for an international address (for example, US:90210)."
        )

    if base == "MOBILE":
        normalized = _normalize_mobile(value)
        if normalized is None:
            return None, "Enter a valid mobile number for its country."
        return normalized, None

    if base == "ACCOUNT_NUMBER":
        normalized = re.sub(r"[\s-]", "", value).upper()
        if (
            not 4 <= len(normalized) <= 34
            or not re.fullmatch(r"[A-Z0-9]+", normalized)
            or not re.search(r"[0-9]", normalized)
        ):
            return None, (
                "Account number must contain 4 to 34 ASCII letters or digits, "
                "including at least one digit."
            )
        return normalized, None
    if base == "CARD_NO":
        normalized = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"[0-9]{12,19}", normalized):
            return None, "Enter the complete card number (12 to 19 digits)."
        if not _luhn_valid(normalized):
            return None, "Card number failed the Luhn checksum."
        # The persistence layer encrypts this complete value before storage.
        return normalized, None

    if base == "CREDIT_CARD_NUMBER":
        from pdfunlocker.profiles.card_crypto import is_encrypted_card
        if is_encrypted_card(value):
            return value, None
        normalized = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"[0-9]{12,19}", normalized) or not _luhn_valid(normalized):
            return None, "Legacy card number must contain 12 to 19 digits and pass the Luhn checksum."
        return normalized, None

    if base in {
        "BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR",
        "AADHAAR_FIRST4", "AADHAAR_LAST4",
    }:
        if not re.fullmatch(r"[0-9]+", value):
            return None, f"{base} must contain ASCII digits only."

        number = int(value)
        if base == "BIRTH_DAY" and not 1 <= number <= 31:
            return None, "BIRTH_DAY must be between 1 and 31."
        if base == "BIRTH_MONTH" and not 1 <= number <= 12:
            return None, "BIRTH_MONTH must be between 1 and 12."
        if base == "BIRTH_YEAR":
            current_year = date.today().year
            if len(value) != 4 or not 1900 <= number <= current_year:
                return None, f"BIRTH_YEAR must be between 1900 and {current_year}."
        if base in {"AADHAAR_FIRST4", "AADHAAR_LAST4"} and len(value) != 4:
            return None, f"{base} must contain exactly 4 digits."
        return value, None

    if base in {
        "CIF", "POLICY_NUMBER", "PPO_NUMBER", "EMPLOYEE_ID",
        "ROLL_NUMBER", "CUSTOMER_ID",
    }:
        normalized = re.sub(r"\s+", "", value).upper()
        if (
            not 1 <= len(normalized) <= 128
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9./-]*", normalized)
        ):
            return None, (
                f"{base} must be 1 to 128 letters, digits, dots, slashes, or hyphens."
            )
        return normalized, None

    if "\x00" in value:
        return None, "Custom field values cannot contain a NUL character."

    return value, None


def validate_field_value(field: str, value: str) -> tuple[str | None, str | None]:
    """Public, non-interactive validator reusable by CLI, API, and Enterprise Mode."""
    return _validate_and_normalize(field, value)


def validate_profile_values(values: dict[str, str]) -> list[str]:
    """Validate a complete profile without I/O or mutation.

    Optional empty values are ignored. Aadhaar is accepted here only in its
    masked storage form. Archived legacy fields are not individually validated.
    For backward compatibility, a complete legacy BIRTH_DAY/BIRTH_MONTH/
    BIRTH_YEAR triplet is still checked as one calendar date. Incomplete
    legacy triplets are ignored, matching the existing profile-manager contract.
    """
    errors: list[str] = []

    archived_legacy_fields = {
        "ACCOUNT_TITLE",
        "BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR",
        "AADHAAR_FIRST4", "AADHAAR_LAST4",
        "INCORPORATION_DAY", "INCORPORATION_MONTH", "INCORPORATION_YEAR",
        "ROLL_NUMBER",
    }

    # Keep the historical split-DOB compatibility check without changing the
    # manager, field registry, database schema, or active DOB field definition.
    # Archived non-date text is ignored; a numeric triplet is treated as a date
    # and must be a valid calendar date.
    legacy_dob_fields = ("BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR")
    if all(field in values and values[field] not in (None, "") for field in legacy_dob_fields):
        day_text = values["BIRTH_DAY"]
        month_text = values["BIRTH_MONTH"]
        year_text = values["BIRTH_YEAR"]
        if all(
            isinstance(item, str) and re.fullmatch(r"[0-9]+", item)
            for item in (day_text, month_text, year_text)
        ):
            try:
                day, month, year = int(day_text), int(month_text), int(year_text)
                if len(year_text) != 4 or not 1900 <= year <= date.today().year:
                    raise ValueError
                date(year, month, day)
            except (TypeError, ValueError):
                errors.append(
                    "DATE_OF_BIRTH: complete legacy birth day, month, and year "
                    "must form a valid calendar date."
                )

    for field, value in values.items():
        if field in {"PROFILE_ID", "PROFILE_NAME"} | archived_legacy_fields:
            # Retired values remain preserved; the complete legacy DOB triplet
            # is handled together above for backward compatibility only.
            continue

        from pdfunlocker.profiles.card_crypto import is_card_field_key, is_encrypted_card
        if is_card_field_key(field) and (
            is_encrypted_card(value) or _valid_masked_card(value)
        ):
            continue
        normalized, error = _validate_and_normalize(
            field, value, allow_masked_aadhaar=(field.split("_", 1)[0] == "AADHAAR")
        )
        if error:
            errors.append(f"{field}: {error}")
        elif normalized != value:
            errors.append(f"{field}: normalization required.")

    return errors
