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

VALID_COUNTRY_CALLING_CODES = frozenset("""
1 7 20 27 30 31 32 33 34 36 39 40 41 43 44 45 46 47 48 49
51 52 53 54 55 56 57 58 60 61 62 63 64 65 66 81 82 84 86
90 91 92 93 94 95 98
211 212 213 216 218
220 221 222 223 224 225 226 227 228 229
230 231 232 233 234 235 236 237 238 239
240 241 242 243 244 245 246 247 248 249
250 251 252 253 254 255 256 257 258 260
261 262 263 264 265 266 267 268 269
290 291 297 298 299
350 351 352 353 354 355 356 357 358 359
370 371 372 373 374 375 376 377 378 380
381 382 383 385 386 387 389
420 421 423
500 501 502 503 504 505 506 507 508 509
590 591 592 593 594 595 596 597 598 599
670 672 673 674 675 676 677 678 679
680 681 682 683 685 686 687 688 689 690
691 692
850 852 853 855 856 880 886
960 961 962 963 964 965 966 967 968 970
971 972 973 974 975 976 977
992 993 994 995 996 998
""".split())

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


def _normalize_mobile(value: str) -> str | None:
    """Validate a country-specific mobile number and return E.164 format."""
    candidate = value.strip()
    if not candidate:
        return None

    if candidate.startswith("00"):
        candidate = "+" + candidate[2:]

    # Bare Indian national numbers are interpreted using India's numbering plan.
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
    field: str, value: str
) -> tuple[str | None, str | None]:
    """Pure profile-field validation. Returns (normalized_value, error)."""
    if not isinstance(field, str) or not isinstance(value, str):
        return None, "Field name and value must be text."

    base = re.sub(r"_\d+$", "", field).upper()

    if value == "":
        return "", None

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

    value = value.strip()
    if not value:
        return "", None

    if base == "TITLE":
        normalized = value.upper()
        if normalized not in {"MR", "MRS", "MS", "MISS", "DR", "OTHER"}:
            return None, "Choose one of: Mr, Mrs, Ms, Miss, Dr, Other."
        return ("Dr" if normalized == "DR" else normalized.title()), None

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
        normalized = re.sub(r"\s+", " ", value).strip()
        compact = normalized.replace(" ", "").replace("-", "")
        if (
            not 2 <= len(compact) <= 12
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 -]*[A-Za-z0-9]", normalized)
        ):
            return None, "Enter a valid international postal or ZIP code."
        return normalized.upper(), None

    if base == "MOBILE":
        normalized = _normalize_mobile(value)
        if normalized is None:
            return None, "Enter a valid mobile number for its country."
        return normalized, None

    if base == "ACCOUNT_NUMBER":
        normalized = re.sub(r"[\s-]", "", value).upper()
        if (
            not 4 <= len(normalized) <= 34
            or not normalized.isalnum()
            or not any(char.isdigit() for char in normalized)
        ):
            return None, (
                "Account number must contain 4 to 34 letters or digits, "
                "including at least one digit."
            )
        return normalized, None

    if base == "CREDIT_CARD_NUMBER":
        normalized = re.sub(r"[\s-]", "", value)
        if not re.fullmatch(r"[0-9]{12,19}", normalized):
            return None, "Card number must contain 12 to 19 digits."
        if not _luhn_valid(normalized):
            return None, "Card number failed the Luhn checksum."
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

    Optional empty values are ignored. DOB cross-field validation runs only
    when day, month, and year are all supplied.
    """
    errors: list[str] = []

    for field, value in values.items():
        if field in {"PROFILE_ID", "PROFILE_NAME", "ACCOUNT_TITLE"}:
            # ACCOUNT_TITLE is a retired input field; keep legacy values intact.
            continue

        normalized, error = _validate_and_normalize(field, value)
        if error:
            errors.append(f"{field}: {error}")
        elif normalized != value:
            errors.append(f"{field}: normalization required.")

    day = values.get("BIRTH_DAY", "").strip()
    month = values.get("BIRTH_MONTH", "").strip()
    year = values.get("BIRTH_YEAR", "").strip()

    if day and month and year:
        try:
            date(int(year), int(month), int(day))
        except (ValueError, TypeError):
            errors.append(
                "DATE_OF_BIRTH: day, month, and year do not form a valid calendar date."
            )

    return errors
