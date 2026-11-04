"""Permanent public field identifiers for PDF Unlocker profiles.

`field_number` remains an internal SQLite key for compatibility. `field_id` is
 the stable public identifier used by users and password rules.
"""
from __future__ import annotations

import re

FIELD_ID_BY_KEY = {
    "TITLE": "0100",
    "FIRST_NAME": "0200",
    "LAST_NAME": "0300",
    "MIDDLE_NAME": "0400",
    "MOTHER_NAME": "0500",
    "DOB": "0600",
    "MOBILE": "0700",
    "EMAIL": "0800",
    "PINCODE": "0900",
    "PAN": "1000",
    "AADHAAR": "1100",
    "INCORPORATION_DATE": "1700",
    "TAN": "1800",
    "GSTIN": "1900",
    "EMPLOYEE_ID": "2000",
    "UAN": "2100",
    "PPO_NUMBER": "2200",
    "PRAN": "2300",
    "POLICY_NUMBER": "2400",
}

BANK_SUFFIXES = {
    "A": ("BANK_NAME", "Bank Name", False),
    "B": ("IFSC", "IFSC", True),
    "C": ("CIF", "CIF", True),
    "D": ("CUSTOMER_ID", "Customer ID", True),
    "E": ("ACCOUNT_NUMBER", "Account Number", True),
    "F": ("CARD_NO", "Card Number (full; encrypted)", True),
}
BANK_FIRST = 1200
BANK_LAST = 1699

LEGACY_FIELD_KEYS = {
    "BIRTH_MONTH", "BIRTH_YEAR", "BIRTH_DAY", "ACCOUNT_NUMBER",
    "CREDIT_CARD_NUMBER", "CUSTOMER_ID", "AADHAAR_FIRST4",
    "AADHAAR_LAST4", "EMPLOYEE_ID", "ROLL_NUMBER", "IFSC", "CIF",
    "ACCOUNT_TITLE", "POLICY_NUMBER", "PPO_NUMBER", "UAN", "PRAN",
    "TAN", "GSTIN", "INCORPORATION_DAY", "INCORPORATION_MONTH",
    "INCORPORATION_YEAR",
}

# Old three-digit field IDs are retained only as compatibility aliases. Active
# rules are migrated to the permanent IDs below.
LEGACY_FIELD_ID_MAP = {
    "001": "0200", "002": "0700", "003": "0300", "004": "0800",
    "005": "0900", "006": "1200E", "007": "1200F", "008": "1200D",
    "009": "0600", "012": "0400", "013": "0500", "014": "1000",
    "015": "1100", "016": "1100", "017": "2000", "019": "1200B",
    "020": "1200C", "022": "2100", "023": "2300", "024": "2400",
    "025": "2200", "026": "1800", "027": "1900", "031": "0100",
}


def bank_field_key(group: int, suffix: str) -> str:
    if not BANK_FIRST <= int(group) <= BANK_LAST or suffix not in BANK_SUFFIXES:
        raise ValueError("Bank group must be 1200-1699 and suffix must be A-F")
    return f"BANK_{int(group)}{suffix}"


def bank_field_id(group: int, suffix: str) -> str:
    bank_field_key(group, suffix)
    return f"{int(group)}{suffix}"


def normalize_field_id(value: object, *, allow_legacy: bool = True) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip().upper()
    if allow_legacy and text.isdigit() and len(text) <= 3 and 1 <= int(text) <= 999:
        return f"{int(text):03d}"
    if re.fullmatch(r"(?:0[1-9]00|1[01]00|1[7-9]00|2[0-4]00)", text):
        return text
    if re.fullmatch(r"1[2-6][0-9]{2}[A-F]", text):
        group = int(text[:4])
        return text if BANK_FIRST <= group <= BANK_LAST else None
    if re.fullmatch(r"CUSTOM[0-9]{4,}", text):
        return text
    return None


def field_id_for_key(field_key: str, field_number: int, *, is_custom: bool = False) -> str:
    if field_key in FIELD_ID_BY_KEY:
        return FIELD_ID_BY_KEY[field_key]
    match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})([A-F])", field_key)
    if match and BANK_FIRST <= int(match.group(1)) <= BANK_LAST:
        return f"{match.group(1)}{match.group(2)}"
    if is_custom:
        return f"CUSTOM{int(field_number):04d}"
    # Preserve a deterministic legacy identifier for archived definitions.
    return f"{int(field_number):03d}" if field_key in LEGACY_FIELD_KEYS else f"CUSTOM{int(field_number):04d}"
