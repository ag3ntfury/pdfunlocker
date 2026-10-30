from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from itertools import product

from pdfunlocker.profiles.manager import get_profile
from pdfunlocker.rules.manager import Rule, load_executable_rules


@dataclass(frozen=True)
class Candidate:
    password: str
    rule: Rule


@dataclass(frozen=True)
class RuleEvaluation:
    rule: Rule
    applicable: bool
    reason: str
    candidate_count: int


def _values(profile: dict[str, str], prefix: str) -> list[str]:
    fields = [
        key
        for key in profile
        if key.startswith(f"{prefix}_")
        and key[len(prefix) + 1:].isdigit()
    ]
    fields.sort(key=lambda key: int(key.rsplit("_", 1)[1]))
    return [profile[key] for key in fields if profile[key]]


def _first(value: str, count: int) -> str:
    return value[:count]


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _date_parts(profile: dict[str, str]) -> tuple[int, int, int] | None:
    day = profile.get("BIRTH_DAY", "").strip()
    month = profile.get("BIRTH_MONTH", "").strip()
    year = profile.get("BIRTH_YEAR", "").strip()

    if not (day.isdigit() and month.isdigit() and year.isdigit()):
        return None

    if not (len(year) == 4 and 1 <= int(day) <= 31 and 1 <= int(month) <= 12):
        return None

    return int(day), int(month), int(year)


def _dob(profile: dict[str, str], fmt: str) -> list[str]:
    parts = _date_parts(profile)
    if parts is None:
        return []

    day, month, year = parts
    yy = year % 100

    formats: dict[str, str] = {
        "DDMM": f"{day:02d}{month:02d}",
        "DDMMYY": f"{day:02d}{month:02d}{yy:02d}",
        "DDMMYYYY": f"{day:02d}{month:02d}{year:04d}",
        "MMDD": f"{month:02d}{day:02d}",
        "YYYY": f"{year:04d}",
        "YYYYMMDD": f"{year:04d}{month:02d}{day:02d}",
    }

    value = formats.get(fmt)
    return [value] if value else []


def _month_name(profile: dict[str, str], short: bool = True) -> list[str]:
    parts = _date_parts(profile)
    if parts is None:
        return []

    month = parts[1]
    name = calendar.month_name[month]
    return [name[:3] if short else name]


def _email_values(profile: dict[str, str]) -> list[str]:
    return _values(profile, "EMAIL")


def _mobile_values(profile: dict[str, str]) -> list[str]:
    return _values(profile, "MOBILE")


def _account_values(profile: dict[str, str]) -> list[str]:
    return _values(profile, "ACCOUNT_NUMBER")


def _card_values(profile: dict[str, str]) -> list[str]:
    return _values(profile, "CREDIT_CARD_NUMBER")


def _customer_values(profile: dict[str, str]) -> list[str]:
    return _values(profile, "CUSTOMER_ID")


def _email_local(value: str) -> str:
    return value.split("@", 1)[0] if "@" in value else ""


def _email_domain(value: str) -> str:
    return value.split("@", 1)[1] if "@" in value else ""


def _initials(profile: dict[str, str], count: int) -> list[str]:
    parts = [
        profile.get("FIRST_NAME", "").strip(),
        profile.get("MIDDLE_NAME", "").strip(),
        profile.get("LAST_NAME", "").strip(),
    ]
    letters = "".join(part[0] for part in parts if part)
    return [letters[:count]] if len(letters) >= count else []


def _incorporation_date_parts(
    profile: dict[str, str],
) -> tuple[int, int, int] | None:
    try:
        day_text = profile.get("INCORPORATION_DAY", "").strip()
        month_text = profile.get("INCORPORATION_MONTH", "").strip()
        year_text = profile.get("INCORPORATION_YEAR", "").strip()
        if not (day_text.isdigit() and month_text.isdigit()):
            return None
        if not year_text.isdigit() or len(year_text) != 4:
            return None
        day, month, year = int(day_text), int(month_text), int(year_text)
        if not 1 <= day <= 31 or not 1 <= month <= 12:
            return None
        return day, month, year
    except (TypeError, ValueError):
        return None


def _resolve_component(component: str, profile: dict[str, str]) -> list[str]:
    if component.startswith("literal:"):
        return [component.split(":", 1)[1]]

    if component == "first_name":
        value = profile.get("FIRST_NAME", "")
        return [value] if value else []

    if component == "last_name":
        value = profile.get("LAST_NAME", "")
        return [value] if value else []

    if component == "pan":
        value = profile.get("PAN", "")
        return [value] if value else []

    if component == "pincode":
        value = profile.get("PINCODE", "")
        return [value] if value else []

    if component == "customer_id":
        return _customer_values(profile)

    if component == "customer_id:digits":
        return [_digits(v) for v in _customer_values(profile)]

    if component == "customer_id:first4":
        return [_first(v, 4) for v in _customer_values(profile) if len(v) >= 4]

    if component == "customer_id:last4":
        return [v[-4:] for v in _customer_values(profile) if len(v) >= 4]

    if component == "account_number":
        return _account_values(profile)

    if component == "account_number:digits":
        return [_digits(v) for v in _account_values(profile)]

    if component == "account_number:first6":
        return [v[:6] for v in _account_values(profile) if len(v) >= 6]

    if component == "account_number:last4":
        return [v[-4:] for v in _account_values(profile) if len(v) >= 4]

    if component == "account_number:last6":
        return [v[-6:] for v in _account_values(profile) if len(v) >= 6]

    if component == "credit_card_number:last4":
        return [v[-4:] for v in _card_values(profile) if len(v) >= 4]

    if component == "mobile:full_country_code":
        return _mobile_values(profile)

    if component == "mobile:full_without_country_code":
        return [_digits(v)[2:] if _digits(v).startswith("91") else _digits(v)
                for v in _mobile_values(profile)]

    if component == "mobile:digits":
        return [_digits(v) for v in _mobile_values(profile)]

    if component == "mobile:last4":
        return [_digits(v)[-4:] for v in _mobile_values(profile)]

    if component == "mobile:last5":
        return [_digits(v)[-5:] for v in _mobile_values(profile)]

    if component == "mobile:last6":
        return [_digits(v)[-6:] for v in _mobile_values(profile)]

    if component == "email:local":
        return [_email_local(v) for v in _email_values(profile) if _email_local(v)]

    if component == "email:local_digits":
        return [_digits(_email_local(v)) for v in _email_values(profile)]

    if component == "email:domain":
        return [_email_domain(v) for v in _email_values(profile) if _email_domain(v)]

    if component == "first_name:first2":
        value = profile.get("FIRST_NAME", "")
        return [_first(value, 2)] if len(value) >= 2 else []

    if component == "first_name:first4":
        value = profile.get("FIRST_NAME", "")
        return [_first(value, 4)] if len(value) >= 4 else []

    if component == "last_name:first4":
        value = profile.get("LAST_NAME", "")
        return [_first(value, 4)] if len(value) >= 4 else []

    if component == "initials:first2":
        return _initials(profile, 2)

    if component == "initials:first3":
        return _initials(profile, 3)

    if component == "pan:first4":
        value = profile.get("PAN", "")
        return [_first(value, 4)] if len(value) >= 4 else []

    if component == "pan:first5":
        value = profile.get("PAN", "")
        return [_first(value, 5)] if len(value) >= 5 else []

    if component == "pan:last4":
        value = profile.get("PAN", "")
        return [value[-4:]] if len(value) >= 4 else []

    if component == "dob:DDMM":
        return _dob(profile, "DDMM")

    if component == "dob:DDMMYY":
        return _dob(profile, "DDMMYY")

    if component == "dob:DDMMYYYY":
        return _dob(profile, "DDMMYYYY")

    if component == "dob:MMDD":
        return _dob(profile, "MMDD")

    if component == "dob:YYYY":
        return _dob(profile, "YYYY")

    if component == "dob:YYYYMMDD":
        return _dob(profile, "YYYYMMDD")

    if component == "birth_month:first3":
        return _month_name(profile)

    if component == "employee_id":
        value = profile.get("EMPLOYEE_ID", "")
        return [value] if value else []

    if component == "employee_id:last2":
        value = profile.get("EMPLOYEE_ID", "")
        return [value[-2:]] if len(value) >= 2 else []

    if component == "employee_id:last4":
        value = profile.get("EMPLOYEE_ID", "")
        return [value[-4:]] if len(value) >= 4 else []

    direct_fields = {
        "ifsc": "IFSC",
        "cif": "CIF",
        "uan": "UAN",
        "pran": "PRAN",
        "tan": "TAN",
        "gstin": "GSTIN",
        "policy_number": "POLICY_NUMBER",
        "ppo_number": "PPO_NUMBER",
        "roll_number": "ROLL_NUMBER",
    }
    if component in direct_fields:
        value = profile.get(direct_fields[component], "").strip()
        return [value] if value else []

    if component == "account_title:first4":
        value = profile.get("ACCOUNT_TITLE", "").strip()
        return [value[:4]] if len(value) >= 4 else []

    if component == "mother_name:first_name":
        value = profile.get("MOTHER_NAME", "").strip()
        first = value.split()[0] if value else ""
        return [first] if first else []

    if component in {
        "date_of_incorporation:DDMM",
        "date_of_incorporation:DDMMYYYY",
    }:
        parts = _incorporation_date_parts(profile)
        if parts is None:
            return []
        day, month, year = parts
        if component == "date_of_incorporation:DDMM":
            return [f"{day:02d}{month:02d}"]
        return [f"{day:02d}{month:02d}{year:04d}"]

    return []


def _apply_case(value: str, case: str) -> str:
    if case == "capitalize":
        return value.capitalize()
    if case == "lower":
        return value.lower()
    if case == "upper":
        return value.upper()
    if case == "raw":
        return value
    raise ValueError(f"Unsupported case transformation: {case}")


def _resolve_field_part(part, profile: dict[str, str]) -> list[str]:
    from pdfunlocker.profiles import store

    definitions = store.list_fields(include_archived=False)
    definition = next(
        (
            item for item in definitions
            if f"{int(item['field_number']):03d}" == part.field_id
        ),
        None,
    )
    if definition is None:
        return []

    key = str(definition["field_key"])
    values: list[tuple[int, str]] = []

    base_value = profile.get(key, "")
    if base_value:
        values.append((0, base_value))

    if definition.get("allows_multiple"):
        prefix = f"{key}_"
        for profile_key, value in profile.items():
            if (
                profile_key.startswith(prefix)
                and profile_key[len(prefix):].isdigit()
                and int(profile_key[len(prefix):]) > 0
                and value
            ):
                values.append((int(profile_key[len(prefix):]), value))

    values.sort(key=lambda item: item[0])
    resolved: list[str] = []
    for _sequence, value in values:
        if part.mode == "first":
            value = value[:part.count]
        elif part.mode == "last":
            value = value[-part.count:]
        if value:
            resolved.append(value)
    return resolved


def _resolve_rule_components(
    rule: Rule, profile: dict[str, str]
) -> tuple[list[list[str]], str]:
    component_values: list[list[str]] = []

    if rule.fields:
        for part in rule.fields:
            values = _resolve_field_part(part, profile)
            if not values:
                return [], f"missing profile value for field '{part.field_id}'"
            component_values.append(values)
    else:
        for component in rule.components:
            values = _resolve_component(component, profile)
            if not values:
                return [], f"missing profile value for component '{component}'"
            component_values.append(values)

    return component_values, ""


def iter_rule_candidates(rule: Rule, profile: dict[str, str]):
    """Yield every distinct candidate without materializing the full result."""
    component_values, reason = _resolve_rule_components(rule, profile)
    if reason:
        return

    seen: set[str] = set()
    cases = rule.cases or (rule.case,)
    for parts in product(*component_values):
        combined = "".join(parts)
        for case in cases:
            password = _apply_case(combined, case)
            if password and password not in seen:
                seen.add(password)
                yield Candidate(password=password, rule=rule)


def generate_rule_candidates(
    rule: Rule,
    profile: dict[str, str],
    *,
    max_candidates: int | None = None,
) -> tuple[list[Candidate], str]:
    """Return candidates; unlimited by default, with an optional explicit limit."""
    if max_candidates is not None:
        if (
            isinstance(max_candidates, bool)
            or not isinstance(max_candidates, int)
            or max_candidates <= 0
        ):
            raise ValueError("max_candidates must be a positive integer")

    component_values, reason = _resolve_rule_components(rule, profile)
    if reason:
        return [], reason

    candidates: list[Candidate] = []
    seen: set[str] = set()
    cases = rule.cases or (rule.case,)
    for parts in product(*component_values):
        combined = "".join(parts)
        for case in cases:
            password = _apply_case(combined, case)
            if not password or password in seen:
                continue
            seen.add(password)
            candidates.append(Candidate(password=password, rule=rule))
            if max_candidates is not None and len(candidates) >= max_candidates:
                return candidates, f"{len(candidates)} candidate(s)"

    if not candidates:
        return [], "rule produced no candidates"
    return candidates, f"{len(candidates)} candidate(s)"

def evaluate_rules_for_profile(
    profile_id: int,
    *,
    max_candidates_per_rule: int | None = None,
) -> tuple[dict[str, str], list[RuleEvaluation], list[Candidate]]:
    profile_result = get_profile(profile_id)

    if profile_result is None:
        raise ValueError(f"profile not found: {profile_id}")

    _path, profile = profile_result
    rules = load_executable_rules()

    evaluations: list[RuleEvaluation] = []
    candidates: list[Candidate] = []

    for rule in rules:
        rule_candidates, reason = generate_rule_candidates(
            rule,
            profile,
            max_candidates=max_candidates_per_rule,
        )

        applicable = bool(rule_candidates)

        evaluations.append(
            RuleEvaluation(
                rule=rule,
                applicable=applicable,
                reason=reason,
                candidate_count=len(rule_candidates),
            )
        )

        candidates.extend(rule_candidates)

    return profile, evaluations, candidates
