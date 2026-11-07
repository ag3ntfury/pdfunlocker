"""Permanent global field identifiers for PDF Unlocker profiles.

Field IDs identify field *types*. Profile values receive an alphabetic suffix
at runtime (for example, 4424A and 4424B). Bank-group identifiers are legacy
storage/ownership keys only; they resolve to one shared banking field ID.
"""
from __future__ import annotations

import re
import secrets

GROUP_RANGES = {
    "PERSONAL": (1001, 3000),
    "PRIVATE": (3001, 4000),
    "BANKING": (4001, 6000),
    "BUSINESS": (6001, 7000),
    "EMPLOYMENT": (7001, 8000),
    "INSURANCE": (8001, 9000),
    "EDUCATION": (9001, 10000),
}

# Deliberately irregular assignments. Consecutive built-in IDs are separated
# by 41-80 numbers; IDs are permanent once published.
FIELD_ID_BY_KEY = {
    # PERSONAL: 1001-3000
    "TITLE": "1173",
    "FIRST_NAME": "1248",
    "MIDDLE_NAME": "1302",
    "LAST_NAME": "1371",
    "MOTHER_NAME": "1429",
    "DOB": "1506",
    "MOBILE": "1578",
    "EMAIL": "1641",
    "PINCODE": "1705",
    "BIRTH_DAY": "1762",
    "BIRTH_MONTH": "1829",
    "BIRTH_YEAR": "1883",
    # PRIVATE: 3001-4000
    "PAN": "3197",
    "AADHAAR": "3268",
    "AADHAAR_FIRST4": "3324",
    "AADHAAR_LAST4": "3396",
    # BANKING: 4001-6000
    "BANK_NAME": "4169",
    "IFSC": "4223",
    "CIF": "4298",
    "CUSTOMER_ID": "4356",
    "ACCOUNT_NUMBER": "4424",
    "CREDIT_CARD_NUMBER": "4487",
    "CARD_NO": "4487",
    "CARD_NUMBER": "4487",
    "ACCOUNT_TITLE": "4553",
    "BRANCH": "4614",
    "ACCOUNT_TYPE": "4678",
    # BUSINESS: 6001-7000
    "INCORPORATION_DATE": "6137",
    "TAN": "6194",
    "GSTIN": "6267",
    "BUSINESS_NAME": "6335",
    "BUSINESS_REGISTRATION_NUMBER": "6394",
    "INCORPORATION_DAY": "6459",
    "INCORPORATION_MONTH": "6521",
    "INCORPORATION_YEAR": "6584",
    # EMPLOYMENT: 7001-8000
    "EMPLOYEE_ID": "7141",
    "UAN": "7204",
    "PPO_NUMBER": "7276",
    "PRAN": "7331",
    # INSURANCE: 8001-9000
    "POLICY_NUMBER": "8173",
    "INSURER_NAME": "8234",
    "POLICY_TYPE": "8296",
    # EDUCATION: 9001-10000
    "ROLL_NUMBER": "9178",
    "INSTITUTION_NAME": "9234",
    "QUALIFICATION": "9298",
    "COURSE": "9366",
    "ENROLLMENT_NUMBER": "9427",
    "REGISTRATION_NUMBER": "9482",
}

FIELD_CATEGORY_BY_KEY = {
    key: group
    for group, keys in {
        "PERSONAL": (
            "TITLE", "FIRST_NAME", "MIDDLE_NAME", "LAST_NAME", "MOTHER_NAME",
            "DOB", "MOBILE", "EMAIL", "PINCODE", "BIRTH_DAY", "BIRTH_MONTH", "BIRTH_YEAR",
        ),
        "PRIVATE": ("PAN", "AADHAAR", "AADHAAR_FIRST4", "AADHAAR_LAST4"),
        "BANKING": (
            "BANK_NAME", "IFSC", "CIF", "CUSTOMER_ID", "ACCOUNT_NUMBER",
            "CREDIT_CARD_NUMBER", "CARD_NO", "CARD_NUMBER", "ACCOUNT_TITLE",
            "BRANCH", "ACCOUNT_TYPE",
        ),
        "BUSINESS": (
            "INCORPORATION_DATE", "TAN", "GSTIN", "BUSINESS_NAME",
            "BUSINESS_REGISTRATION_NUMBER", "INCORPORATION_DAY",
            "INCORPORATION_MONTH", "INCORPORATION_YEAR",
        ),
        "EMPLOYMENT": ("EMPLOYEE_ID", "UAN", "PPO_NUMBER", "PRAN"),
        "INSURANCE": ("POLICY_NUMBER", "INSURER_NAME", "POLICY_TYPE"),
        "EDUCATION": (
            "ROLL_NUMBER", "INSTITUTION_NAME", "QUALIFICATION", "COURSE",
            "ENROLLMENT_NUMBER", "REGISTRATION_NUMBER",
        ),
    }.items()
    for key in keys
}

BANK_SUFFIXES = {
    "A": ("BANK_NAME", "Bank Name", True),
    "B": ("IFSC", "IFSC", True),
    "C": ("CIF", "CIF", True),
    "D": ("CUSTOMER_ID", "Customer ID", True),
    "E": ("ACCOUNT_NUMBER", "Account Number", True),
    "F": ("CARD_NUMBER", "Card Number (full; encrypted)", True),
}
# These are internal legacy group tokens, not public field IDs.
BANK_FIRST = 1200
BANK_LAST = 1699
BANK_SUFFIX_BY_FIELD_KEY = {
    "BANK_NAME": "A",
    "IFSC": "B",
    "CIF": "C",
    "CUSTOMER_ID": "D",
    "ACCOUNT_NUMBER": "E",
    "CREDIT_CARD_NUMBER": "F",
    "CARD_NO": "F",
    "CARD_NUMBER": "F",
}

LEGACY_FIELD_KEYS = {
    "BIRTH_MONTH", "BIRTH_YEAR", "BIRTH_DAY", "ACCOUNT_NUMBER",
    "CREDIT_CARD_NUMBER", "CUSTOMER_ID", "AADHAAR_FIRST4",
    "AADHAAR_LAST4", "EMPLOYEE_ID", "ROLL_NUMBER", "IFSC", "CIF",
    "ACCOUNT_TITLE", "POLICY_NUMBER", "PPO_NUMBER", "UAN", "PRAN",
    "TAN", "GSTIN", "INCORPORATION_DAY", "INCORPORATION_MONTH",
    "INCORPORATION_YEAR",
}

# Compatibility aliases from both the original three-digit registry and the
# intermediate 2026 registry. They are normalized to the new permanent IDs.
LEGACY_FIELD_ID_MAP = {
    "001": FIELD_ID_BY_KEY["FIRST_NAME"],
    "002": FIELD_ID_BY_KEY["MOBILE"],
    "003": FIELD_ID_BY_KEY["LAST_NAME"],
    "004": FIELD_ID_BY_KEY["EMAIL"],
    "005": FIELD_ID_BY_KEY["PINCODE"],
    "006": FIELD_ID_BY_KEY["ACCOUNT_NUMBER"],
    "007": FIELD_ID_BY_KEY["CREDIT_CARD_NUMBER"],
    "008": FIELD_ID_BY_KEY["CUSTOMER_ID"],
    "009": FIELD_ID_BY_KEY["BIRTH_DAY"],
    "010": FIELD_ID_BY_KEY["BIRTH_MONTH"],
    "011": FIELD_ID_BY_KEY["BIRTH_YEAR"],
    "012": FIELD_ID_BY_KEY["MIDDLE_NAME"],
    "013": FIELD_ID_BY_KEY["MOTHER_NAME"],
    "014": FIELD_ID_BY_KEY["PAN"],
    "015": FIELD_ID_BY_KEY["AADHAAR_FIRST4"],
    "016": FIELD_ID_BY_KEY["AADHAAR_LAST4"],
    "017": FIELD_ID_BY_KEY["EMPLOYEE_ID"],
    "018": FIELD_ID_BY_KEY["ROLL_NUMBER"],
    "019": FIELD_ID_BY_KEY["IFSC"],
    "020": FIELD_ID_BY_KEY["CIF"],
    "021": FIELD_ID_BY_KEY["ACCOUNT_TITLE"],
    "022": FIELD_ID_BY_KEY["UAN"],
    "023": FIELD_ID_BY_KEY["PRAN"],
    "024": FIELD_ID_BY_KEY["POLICY_NUMBER"],
    "025": FIELD_ID_BY_KEY["PPO_NUMBER"],
    "026": FIELD_ID_BY_KEY["TAN"],
    "027": FIELD_ID_BY_KEY["GSTIN"],
    "028": FIELD_ID_BY_KEY["INCORPORATION_DAY"],
    "029": FIELD_ID_BY_KEY["INCORPORATION_MONTH"],
    "030": FIELD_ID_BY_KEY["INCORPORATION_YEAR"],
    "031": FIELD_ID_BY_KEY["TITLE"],
    "032": FIELD_ID_BY_KEY["BIRTH_DAY"],
    # Intermediate public IDs.
    "0100": FIELD_ID_BY_KEY["TITLE"],
    "0200": FIELD_ID_BY_KEY["FIRST_NAME"],
    "0300": FIELD_ID_BY_KEY["LAST_NAME"],
    "0400": FIELD_ID_BY_KEY["MIDDLE_NAME"],
    "0500": FIELD_ID_BY_KEY["MOTHER_NAME"],
    "0600": FIELD_ID_BY_KEY["DOB"],
    "0700": FIELD_ID_BY_KEY["MOBILE"],
    "0800": FIELD_ID_BY_KEY["EMAIL"],
    "0900": FIELD_ID_BY_KEY["PINCODE"],
    "1000": FIELD_ID_BY_KEY["PAN"],
    "1100": FIELD_ID_BY_KEY["AADHAAR"],
    "1700": FIELD_ID_BY_KEY["INCORPORATION_DATE"],
    "1800": FIELD_ID_BY_KEY["TAN"],
    "1900": FIELD_ID_BY_KEY["GSTIN"],
    "2000": FIELD_ID_BY_KEY["EMPLOYEE_ID"],
    "2100": FIELD_ID_BY_KEY["UAN"],
    "2200": FIELD_ID_BY_KEY["PPO_NUMBER"],
    "2300": FIELD_ID_BY_KEY["PRAN"],
    "2400": FIELD_ID_BY_KEY["POLICY_NUMBER"],
}


def bank_field_key(group: int, suffix: str) -> str:
    if not BANK_FIRST <= int(group) <= BANK_LAST or suffix not in BANK_SUFFIXES:
        raise ValueError(f"Bank group must be {BANK_FIRST}-{BANK_LAST} and suffix must be A-F")
    return f"BANK_{int(group)}{suffix}"


def bank_field_id(group: int, suffix: str) -> str:
    bank_field_key(group, suffix)
    field_key = BANK_SUFFIXES[suffix][0]
    return FIELD_ID_BY_KEY[field_key]


def field_category_for_key(field_key: str) -> str:
    match = re.fullmatch(r"BANK_1[2-6][0-9]{2}([A-F])", field_key)
    if match:
        return "BANKING"
    return FIELD_CATEGORY_BY_KEY.get(field_key, "PERSONAL")


def normalize_field_category(category: str | None, *, allow_legacy: bool = False) -> str:
    """Normalize one of the seven categories.

    ``allow_legacy`` is reserved for reading old database rows that were
    created before category selection became mandatory. New field creation
    must always provide one of the seven supported categories.
    """
    if category is None or not str(category).strip():
        if allow_legacy:
            return "Custom"
        raise ValueError("A field category is required.")
    group = str(category).strip().upper().replace(" ", "_")
    aliases = {
        "IDENTITY": "PRIVATE",
        "FINANCIAL": "BANKING",
        "TAX_&_BUSINESS": "BUSINESS",
        "TAX_AND_BUSINESS": "BUSINESS",
        "BENEFITS_&_RETIREMENT": "EMPLOYMENT",
        "BENEFITS_AND_RETIREMENT": "EMPLOYMENT",
        "POLICY": "INSURANCE",
        "ACADEMIC": "EDUCATION",
    }
    group = aliases.get(group, group)
    if group == "CUSTOM" or group not in GROUP_RANGES:
        if allow_legacy:
            return "Custom"
        allowed = ", ".join(name.title() for name in GROUP_RANGES)
        raise ValueError(f"Choose one of the seven field categories: {allowed}.")
    return group.title()


def allocate_field_id(category: str, used_ids: set[str] | None = None) -> str:
    """Allocate a random permanent numeric ID in a category range.

    Existing IDs are never changed. A new ID is kept at least 41 numeric steps
    from every existing ID in its range. Built-in assignments use irregular
    41-80 step spacing; custom allocations use the remaining available tail.
    """
    canonical_category = normalize_field_category(category)
    group = canonical_category.upper()
    if group not in GROUP_RANGES:
        raise ValueError(f"Unknown field category: {category}")
    low, high = GROUP_RANGES[group]
    occupied = {int(value) for value in (used_ids or set()) if str(value).isdigit()}
    candidates = [n for n in range(low, high + 1) if all(abs(n - old) >= 41 for old in occupied)]
    if not candidates:
        raise ValueError(f"No available permanent IDs remain in {group} range {low}-{high}.")
    # Prefer IDs 41-80 after the current highest ID when possible, preserving
    # room for future additions while retaining an unpredictable assignment.
    highest = max((n for n in occupied if low <= n <= high), default=low - 1)
    preferred = [n for n in candidates if highest < n <= min(high, highest + 80)]
    return str(secrets.choice(preferred or candidates))


def normalize_field_id(
    value: object,
    *,
    allow_legacy: bool = True,
    allow_value_instance: bool = False,
    known_ids: set[str] | None = None,
) -> str | None:
    """Return a canonical *registered field-type* ID, or ``None``.

    The pure default accepts built-in IDs and documented legacy aliases only.
    Callers backed by the profile database should pass ``known_ids`` so
    dynamically allocated custom IDs are accepted only when registered.

    Value-instance IDs (for example ``4424A``) are a different identifier
    namespace. They are rejected by default; callers that explicitly need to
    collapse an instance reference to its field type may opt in with
    ``allow_value_instance=True``. Even then, the base field must be known.
    This function validates syntax and registry membership, not whether a
    particular value instance exists in a particular profile.
    """
    if isinstance(value, bool) or value is None:
        return None

    text = str(value).strip().upper()
    if not text:
        return None

    candidate: str | None = None
    if allow_legacy and text in LEGACY_FIELD_ID_MAP:
        candidate = LEGACY_FIELD_ID_MAP[text]
    else:
        # Old bank-group tokens are compatibility aliases, not public IDs.
        bank_match = re.fullmatch(r"1[2-6][0-9]{2}([A-F])", text)
        if bank_match:
            candidate = FIELD_ID_BY_KEY[BANK_SUFFIXES[bank_match.group(1)][0]]
        else:
            value_match = re.fullmatch(r"([1-9][0-9]{3,4})([A-Z]*)", text)
            if value_match:
                base, suffix = value_match.groups()
                if suffix and not allow_value_instance:
                    return None
                candidate = base
            elif re.fullmatch(r"CUSTOM[0-9]{4,}", text):
                candidate = text

    if candidate is None:
        return None

    if known_ids is not None:
        normalized_known = {str(item).strip().upper() for item in known_ids}
        return candidate if candidate in normalized_known else None

    # Without a database-backed registry, never infer that every number in a
    # category range has been assigned. Only published built-ins are known.
    if candidate in FIELD_ID_BY_KEY.values():
        return candidate
    return None


def field_id_for_key(field_key: str, field_number: int, *, is_custom: bool = False) -> str:
    if field_key in FIELD_ID_BY_KEY:
        return FIELD_ID_BY_KEY[field_key]
    match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})([A-F])", field_key)
    if match:
        return bank_field_id(int(match.group(1)), match.group(2))
    if is_custom:
        return f"CUSTOM{int(field_number):04d}"
    # Archived/unmapped legacy fields keep a deterministic custom identifier.
    return f"CUSTOM{int(field_number):04d}"
