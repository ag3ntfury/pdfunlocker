"""Reusable, non-interactive validation and normalization for profile values.

This module has no CLI prompts, database access, or profile-storage side effects.
Personal Mode and future Enterprise Mode should use these public functions.
"""
from __future__ import annotations

import re
from datetime import date

__all__ = [
    "VALID_COUNTRY_CALLING_CODES",
    "normalize_country_calling_code",
    "validate_field_value",
    "validate_profile_values",
]

# ITU-assigned international country calling codes.
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


def normalize_country_calling_code(value: str) -> str | None:
    """Normalize and validate an international country calling code."""
    value = value.strip()

    if not value:
        return "+91"

    if not re.fullmatch(r"\+?[0-9]{1,3}", value):
        return None

    digits = value.removeprefix("+")

    if digits not in VALID_COUNTRY_CALLING_CODES:
        return None

    return f"+{digits}"


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
    """Normalize a phone number to E.164-like +countrycode format.

    Bare 10-digit numbers default to India. International numbers should use
    +countrycode or 00countrycode to avoid ambiguous national prefixes.
    """
    value = re.sub(r"[\s().-]", "", value)
    if value.startswith("00"):
        value = "+" + value[2:]

    if value.startswith("+"):
        digits = value[1:]
    else:
        digits = value
        if digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        if len(digits) == 12 and digits.startswith("91"):
            pass
        elif len(digits) == 10:
            digits = "91" + digits
        else:
            return None

    if not re.fullmatch(r"[0-9]{7,15}", digits):
        return None

    if not any(
        digits.startswith(code)
        for code in sorted(VALID_COUNTRY_CALLING_CODES, key=len, reverse=True)
    ):
        return None

    return "+" + digits


def _validate_and_normalize(field: str, value: str) -> tuple[str | None, str | None]:
    """Pure profile-field validation. Returns (normalized_value, error)."""
    if not isinstance(field, str) or not isinstance(value, str):
        return None, "Field name and value must be text."

    value = value.strip()
    if not value:
        return "", None

    base = re.sub(r"_\d+$", "", field).upper()

    if base == "TITLE":
        normalized = value.upper()
        if normalized not in {"MR", "MRS", "MS", "MISS", "DR", "OTHER"}:
            return None, "Choose one of: Mr, Mrs, Ms, Miss, Dr, Other."
        return ("Dr" if normalized == "DR" else normalized.title()), None

    if base == "EMAIL":
        if value.count("@") != 1 or any(c.isspace() for c in value):
            return None, "Enter a valid email address."
        local, domain = value.rsplit("@", 1)
        if not local or len(local) > 64 or not domain or "." not in domain:
            return None, "Enter a valid email address."
        if local.startswith(".") or local.endswith(".") or ".." in local:
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
        return f"{local}@{domain}".lower(), None

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
        pattern = r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]"
        if not re.fullmatch(pattern, normalized):
            return None, "GSTIN must match the 15-character Indian GSTIN structure."
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
        return (normalized, None) if normalized is not None else (
            None, "Enter a valid mobile number and country calling code."
        )

    if base == "ACCOUNT_NUMBER":
        normalized = re.sub(r"[\s-]", "", value).upper()
        if (
            not 4 <= len(normalized) <= 34
            or not normalized.isalnum()
            or not any(c.isdigit() for c in normalized)
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
        if base == "BIRTH_DAY" and not 1 <= int(value) <= 31:
            return None, "BIRTH_DAY must be between 1 and 31."
        if base == "BIRTH_MONTH" and not 1 <= int(value) <= 12:
            return None, "BIRTH_MONTH must be between 1 and 12."
        if base == "BIRTH_YEAR" and len(value) != 4:
            return None, "BIRTH_YEAR must contain exactly 4 digits."
        if base in {"AADHAAR_FIRST4", "AADHAAR_LAST4"} and len(value) != 4:
            return None, f"{base} must contain exactly 4 digits."
        return value, None

    if base in {"FIRST_NAME", "MIDDLE_NAME", "LAST_NAME", "MOTHER_NAME"}:
        if not re.fullmatch(r"[A-Za-z. ]+", value) or not re.search(r"[A-Za-z]", value):
            return None, (
                f"{base} may contain English letters (A-Z), spaces, and periods only."
            )
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

    # Custom fields intentionally have no built-in format restrictions.
    # Preserve Unicode and capitalization; trim only surrounding whitespace.
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
            errors.append("DATE_OF_BIRTH: day, month, and year do not form a valid calendar date.")

    return errors
