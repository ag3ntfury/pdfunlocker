from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
import re
import shutil

import yaml


RULES_DIR = Path.home() / ".pdfunlocker" / "rules"


class RuleError(ValueError):
    """Raised when a rule is invalid or cannot be loaded."""


@dataclass(frozen=True)
class FieldPart:
    field_id: str
    mode: str = "full"
    count: int | None = None


@dataclass(frozen=True)
class Rule:
    number: str
    rule_id: str
    name: str
    category: str
    priority: str
    components: tuple[str, ...]
    case: str
    path: Path
    fields: tuple[FieldPart, ...] = ()
    cases: tuple[str, ...] = ()


def _require_string(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuleError(f"{path.name}: '{field}' must be a non-empty string")
    return value.strip()


def _priority_key(priority: str) -> tuple[int, int]:
    priority = priority.strip().upper()
    if priority == "Z":
        return (26, 0)

    # Canonical spellings prevent equivalent priorities such as A01 and A1
    # from bypassing the uniqueness check.
    match = re.fullmatch(r"([A-W])([1-9]|10)|X([1-9][0-9]*)", priority)
    if match:
        if match.group(1):
            letter = match.group(1)
            number = int(match.group(2))
            return (ord(letter) - ord("A"), number)
        # Keep X priorities unlimited in the ordinary supported range.
        try:
            number = int(match.group(3))
        except ValueError as exc:
            raise RuleError("invalid X priority number") from exc
        return (23, number)

    raise RuleError("invalid priority; expected A1-W10, X1-Xn, or Z")


def _rule_paths(root: Path | None = None) -> list[Path]:
    base = root or RULES_DIR
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("rule*.yml") if p.is_file())


def _all_used_numbers() -> list[int]:
    numbers: list[int] = []
    for path in _rule_paths():
        match = re.fullmatch(r"rule(\d{5})", path.stem)
        if match:
            numbers.append(int(match.group(1)))
    return numbers


def _all_used_ids() -> set[str]:
    used: set[str] = set()
    for path in _rule_paths():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            rule_data = data.get("rule", {}) if isinstance(data, dict) else {}
            if not isinstance(rule_data, dict):
                continue
            value = rule_data.get("id")
            if isinstance(value, str) and value.strip():
                used.add(value.casefold())
        except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError):
            # A malformed archived rule must not prevent new rule IDs from being
            # checked against all other readable rules.
            continue
    return used


def _next_available_priority(priority: str, exclude: Path | None = None) -> str:
    priority = priority.strip().upper()
    if priority == "Z":
        return "Z"
    _priority_key(priority)
    used = {
        rule.priority for rule in load_rules()
        if exclude is None or rule.path.resolve() != exclude.resolve()
    }
    letter = priority[0]
    start = int(priority[1:]) + 1
    if "A" <= letter <= "W":
        for number in range(start, 11):
            candidate = f"{letter}{number}"
            if candidate not in used:
                return candidate
        raise RuleError(f"no available priority after {priority}")

    # X priorities are intentionally unbounded: X100000 follows X99999.
    number = start
    while True:
        candidate = f"X{number}"
        if candidate not in used:
            return candidate
        number += 1


def _validate_priority_unique(priority: str, exclude: Path | None = None) -> None:
    priority = priority.strip().upper()
    if priority == "Z":
        return
    for rule in load_rules():
        if exclude is not None and rule.path.resolve() == exclude.resolve():
            continue
        if rule.priority == priority:
            raise RuleError(
                f"priority '{priority}' is already assigned to rule "
                f"{rule.number} ({rule.rule_id})"
            )


def _parse_rule(path: Path) -> Rule:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuleError(f"{path.name}: cannot read rule: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RuleError(f"{path.name}: invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise RuleError(f"{path.name}: root must be a YAML mapping")
    rule_data, pattern_data, transform_data = (
        data.get("rule"), data.get("pattern"), data.get("transform")
    )
    if not isinstance(rule_data, dict):
        raise RuleError(f"{path.name}: missing 'rule' mapping")
    if not isinstance(pattern_data, dict):
        raise RuleError(f"{path.name}: missing 'pattern' mapping")
    if not isinstance(transform_data, dict):
        raise RuleError(f"{path.name}: missing 'transform' mapping")

    number = _require_string(rule_data.get("number"), "rule.number", path)
    rule_id = _require_string(rule_data.get("id"), "rule.id", path)
    name = _require_string(rule_data.get("name"), "rule.name", path)
    category = _require_string(rule_data.get("category", "generic"), "rule.category", path)
    priority = _require_string(rule_data.get("priority", "Z"), "rule.priority", path).upper()

    if not re.fullmatch(r"\d{5}", number):
        raise RuleError(f"{path.name}: 'rule.number' must be exactly 5 digits")
    _priority_key(priority)
    _validate_rule_id(rule_id)

    components: list[str] = []
    fields: list[FieldPart] = []
    components_data = pattern_data.get("components")
    fields_data = pattern_data.get("fields")

    # Keep parsing legacy rules possible, while new rules use the field-ID schema.
    if components_data is not None:
        if not isinstance(components_data, list) or not components_data:
            raise RuleError(f"{path.name}: 'pattern.components' must be a non-empty list")
        for component in components_data:
            if not isinstance(component, str) or not component.strip():
                raise RuleError(f"{path.name}: every component must be a non-empty string")
            components.append(component.strip())
    elif fields_data is not None:
        if not isinstance(fields_data, list) or not fields_data:
            raise RuleError(f"{path.name}: 'pattern.fields' must be a non-empty list")
        for index, item in enumerate(fields_data, start=1):
            if not isinstance(item, dict):
                raise RuleError(f"{path.name}: field item {index} must be a mapping")
            raw_id = item.get("field_id")
            if isinstance(raw_id, int):
                raw_id = str(raw_id)
            if not isinstance(raw_id, str) or not raw_id.isdigit() or not 1 <= int(raw_id) <= 999:
                raise RuleError(f"{path.name}: field item {index} has invalid field_id")
            field_id = f"{int(raw_id):03d}"
            slice_data = item.get("slice", {"mode": "full"})
            if isinstance(slice_data, str):
                slice_data = {"mode": slice_data}
            if not isinstance(slice_data, dict):
                raise RuleError(f"{path.name}: field item {index} slice must be a mapping")
            mode = str(slice_data.get("mode", "full")).strip().lower()
            if mode not in {"full", "first", "last"}:
                raise RuleError(f"{path.name}: field item {index} mode must be full, first, or last")
            part_count = slice_data.get("count")
            if mode == "full":
                if part_count is not None:
                    raise RuleError(f"{path.name}: full slice must not specify count")
                part_count = None
            else:
                if isinstance(part_count, str) and part_count.isdigit():
                    part_count = int(part_count)
                if not isinstance(part_count, int) or isinstance(part_count, bool) or not 1 <= part_count <= 256:
                    raise RuleError(f"{path.name}: first/last slice count must be an integer from 1 to 256")
            fields.append(FieldPart(field_id=field_id, mode=mode, count=part_count))
    else:
        raise RuleError(f"{path.name}: pattern must contain 'fields' or legacy 'components'")

    if "case" in transform_data and "cases" in transform_data:
        raise RuleError(
            f"{path.name}: use either 'transform.case' or 'transform.cases', not both"
        )

    if "cases" in transform_data:
        cases_data = transform_data["cases"]
        if not isinstance(cases_data, list) or not cases_data:
            raise RuleError(f"{path.name}: 'transform.cases' must be a non-empty list")
        parsed_cases: list[str] = []
        for item in cases_data:
            if not isinstance(item, str) or item.strip().lower() not in {"raw", "lower", "upper", "capitalize"}:
                raise RuleError(
                    f"{path.name}: every transform.cases entry must be raw, lower, upper, or capitalize"
                )
            selected = item.strip().lower()
            if selected in parsed_cases:
                raise RuleError(f"{path.name}: duplicate case variant '{selected}'")
            parsed_cases.append(selected)
        cases = tuple(parsed_cases)
    else:
        case = _require_string(
            transform_data.get("case", "raw"), "transform.case", path
        ).lower()
        if case not in {"raw", "lower", "upper", "capitalize"}:
            raise RuleError(
                f"{path.name}: 'transform.case' must be raw, lower, upper, or capitalize"
            )
        cases = (case,)

    case = cases[0]
    expected_filename = f"rule{number}.yml"
    if path.name != expected_filename:
        raise RuleError(f"{path.name}: filename must be '{expected_filename}'")

    return Rule(
        number=number, rule_id=rule_id, name=name, category=category,
        priority=priority, components=tuple(components), case=case,
        path=path, fields=tuple(fields), cases=cases,
    )


def load_rules() -> list[Rule]:
    if not RULES_DIR.exists():
        return []
    # Only root-level YAMLs are active. Archive subdirectories are never loaded.
    rules = [_parse_rule(path) for path in sorted(RULES_DIR.glob("rule*.yml"))]
    return sorted(rules, key=lambda r: (_priority_key(r.priority), int(r.number)))


def load_executable_rules() -> list[Rule]:
    """Return non-Z rules in configured priority and numeric rule order."""
    return [rule for rule in load_rules() if rule.priority != "Z"]


def load_default_rules() -> list[Rule]:
    """Return Z/default rules in numeric rule-number order."""
    return sorted(
        (rule for rule in load_rules() if rule.priority == "Z"),
        key=lambda rule: int(rule.number),
    )


def _ensure_rules_dir() -> None:
    RULES_DIR.mkdir(parents=True, exist_ok=True)


def _find_rule(rule_reference: str) -> Rule:
    reference = rule_reference.strip()
    if not reference:
        raise RuleError("rule reference cannot be empty")
    rules = load_rules()
    if reference.isdigit():
        number = reference.zfill(5)
        matches = [r for r in rules if r.number == number]
    elif reference.lower().startswith("rule") and reference[4:].isdigit():
        number = reference[4:].zfill(5)
        matches = [r for r in rules if r.number == number]
    else:
        matches = [r for r in rules if r.rule_id.casefold() == reference.casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RuleError(f"rule not found: {rule_reference}")
    raise RuleError(f"multiple rules matched: {rule_reference}")


def _next_rule_number() -> str:
    used_numbers = set(_all_used_numbers())
    # Numeric IDs reserve a matching rule number where one can exist. Longer
    # numeric IDs cannot collide with the five-digit rule-number namespace.
    used_ids = {
        int(rule_id) for rule_id in _all_used_ids()
        if rule_id.isdigit() and len(rule_id) <= 5
    }
    next_number = max(used_numbers | used_ids, default=0) + 1
    if next_number > 99999:
        raise RuleError("rule number limit reached")
    return f"{next_number:05d}"


def _prompt_required(prompt: str, default: str | None = None) -> str:
    while True:
        value = input(f"{prompt} [{default}]: ").strip() if default is not None else input(f"{prompt}: ").strip()
        if not value and default is not None:
            value = default
        if value:
            return value
        print("Value cannot be empty.")


def _prompt_optional(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def _validate_rule_id(rule_id: str) -> None:
    if not rule_id or any(char.isspace() for char in rule_id):
        raise RuleError("rule ID must not be empty or contain spaces")
    if any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in rule_id):
        raise RuleError("rule ID may contain only letters, digits, '_' and '-'")


def _profile_fields() -> list[dict[str, Any]]:
    try:
        from pdfunlocker.profiles.store import list_fields
        fields = list_fields(include_archived=False)
    except (ImportError, OSError, ValueError) as exc:
        raise RuleError(f"cannot load profile field registry: {exc}") from exc
    return [field for field in fields if not field.get("archived")]


def _field_index() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for field in _profile_fields():
        number = int(field["field_number"])
        result[f"{number:03d}"] = field
    return result


def _show_field_registry(fields: list[dict[str, Any]]) -> None:
    print("Available profile fields (archived fields excluded):")
    print(f"{'ID':<6} {'MULTI':<7} {'FIELD KEY':<28} LABEL")
    print("-" * 76)
    for field in fields:
        number = int(field["field_number"])
        multiple = "yes" if field.get("allows_multiple") else "no"
        print(f"{number:03d}   {multiple:<7} {str(field['field_key']):<28} {field['label']}")


def _prompt_field_parts() -> list[FieldPart]:
    fields = _profile_fields()
    if not fields:
        raise RuleError("no active profile fields are registered")
    field_map = {f"{int(item['field_number']):03d}": item for item in fields}
    _show_field_registry(fields)
    print()
    while True:
        raw_total = input("How many field components should this rule combine? ").strip()
        try:
            total = int(raw_total)
        except ValueError:
            total = 0
        if 1 <= total <= 20:
            break
        print("Enter a number from 1 to 20.")

    parts: list[FieldPart] = []
    for index in range(1, total + 1):
        while True:
            raw_id = input(f"Component {index} field ID (e.g. 1 or 001): ").strip()
            if raw_id.isdigit():
                field_id = f"{int(raw_id):03d}"
                if field_id in field_map:
                    break
            print("Unknown or archived field ID. Choose an ID from the list.")
        field = field_map[field_id]
        print(f"Selected: {field_id} | {field['label']} ({field['field_key']})")
        while True:
            mode = input("Slice [f=first N, l=last N, a=all/full] (default a): ").strip().lower()
            if mode in {"", "a", "all", "full"}:
                parts.append(FieldPart(field_id, "full", None))
                break
            if mode in {"f", "first"}:
                slice_mode = "first"
            elif mode in {"l", "last"}:
                slice_mode = "last"
            else:
                print("Enter f, l, or a.")
                continue
            raw_count = input("Number of characters (1-256): ").strip()
            try:
                amount = int(raw_count)
            except ValueError:
                amount = 0
            if 1 <= amount <= 256:
                parts.append(FieldPart(field_id, slice_mode, amount))
                break
            print("Enter a number from 1 to 256.")
    return parts


def _parts_to_yaml(parts: tuple[FieldPart, ...] | list[FieldPart]) -> list[dict[str, Any]]:
    result = []
    for part in parts:
        item: dict[str, Any] = {"field_id": part.field_id}
        slice_data: dict[str, Any] = {"mode": part.mode}
        if part.count is not None:
            slice_data["count"] = part.count
        item["slice"] = slice_data
        result.append(item)
    return result


def _write_rule(
    number: str, rule_id: str, name: str, category: str,
    priority: str, parts: list[FieldPart], case: str,
    cases: list[str] | tuple[str, ...] | None = None,
) -> Rule:
    path = RULES_DIR / f"rule{number}.yml"
    transform = (
        {"case": case}
        if cases is None or len(cases) == 1
        else {"cases": list(cases)}
    )
    data = {
        "rule": {"number": number, "id": rule_id, "name": name,
                 "category": category, "priority": priority},
        "pattern": {"fields": _parts_to_yaml(parts)},
        "transform": transform,
    }
    payload = yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
    # Exclusive create prevents silently overwriting an existing rule.
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise RuleError(f"refusing to overwrite existing rule file: {path}") from exc
    try:
        return _parse_rule(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def add_rule() -> None:
    _ensure_rules_dir()
    print("\nAdd Profile-Based PDF Unlocker Rule\n===================================")
    number = _next_rule_number()
    print(f"Next rule number: {number}")
    name = _prompt_required("Rule name")
    category = _prompt_optional("Category", "profile")
    parts = _prompt_field_parts()
    cases = ["capitalize", "upper", "lower"]
    while True:
        priority = _prompt_optional("Priority (A1-W10, X1-Xn, or Z)", "Z").upper()
        try:
            _priority_key(priority)
            _validate_priority_unique(priority)
        except RuleError as exc:
            print(f"Invalid priority: {exc}")
            print("Use A1-W10, X1 or higher, or Z. Please try again.")
            continue
        break

    # One rule number and matching ID for every set of case variants.
    rule_id = number
    _validate_rule_id(rule_id)
    if rule_id.casefold() in _all_used_ids():
        raise RuleError(f"generated rule ID has already been used: {rule_id}")

    rule = _write_rule(
        number, rule_id, name, category, priority, parts, cases[0], cases=cases
    )
    print()
    print(f"Created rule: {rule.number} | {rule.name}")
    print(f"Case variants: {', '.join(cases)}")
    print(f"File: {rule.path}")

def _prompt_existing_parts(rule: Rule) -> list[FieldPart]:
    print("Current field components:")
    for i, part in enumerate(rule.fields, 1):
        suffix = "" if part.count is None else f" {part.count}"
        print(f"  {i}. field {part.field_id}: {part.mode}{suffix}")
    print("To keep the existing field pattern, press Enter.")
    answer = input("Replace field components? [y/N]: ").strip().lower()
    return _prompt_field_parts() if answer in {"y", "yes"} else list(rule.fields)


def modify_rule(rule_reference: str) -> None:
    rule = _find_rule(rule_reference)
    if not rule.fields:
        raise RuleError("This is a legacy component-based rule. Rule compatibility is being handled in a later phase; it was not modified.")
    print(f"\nModify Rule {rule.number}\n=======================")
    print("Press Enter to keep the current value.")
    rule_id = _prompt_optional("Rule ID", rule.rule_id)
    _validate_rule_id(rule_id)
    if rule_id.casefold() != rule.rule_id.casefold() and rule_id.casefold() in _all_used_ids():
        raise RuleError(f"rule ID has already been used: {rule_id}")
    name = _prompt_optional("Rule name", rule.name)
    category = _prompt_optional("Category", rule.category)
    parts = _prompt_existing_parts(rule)

    current_cases = tuple(rule.cases or (rule.case,))
    cases = list(current_cases)

    priority = _prompt_optional("Priority (Z or A1-Xn)", rule.priority).upper()
    _priority_key(priority)
    _validate_priority_unique(priority, exclude=rule.path)
    data = {
        "rule": {"number": rule.number, "id": rule_id, "name": name,
                 "category": category, "priority": priority},
        "pattern": {"fields": _parts_to_yaml(parts)},
        "transform": (
            {"case": cases[0]} if len(cases) == 1 else {"cases": cases}
        ),
    }

    original = rule.path.read_text(encoding="utf-8")
    payload = yaml.safe_dump(data, sort_keys=False, allow_unicode=False)
    rule.path.write_text(payload, encoding="utf-8")
    try:
        _parse_rule(rule.path)
    except Exception:
        rule.path.write_text(original, encoding="utf-8")
        raise

    print(f"Rule updated: rule{rule.number}")
    print(f"Case variants: {', '.join(cases)}")

def archive_rule(rule_reference: str) -> None:
    rule = _find_rule(rule_reference)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = RULES_DIR / f"archive-{stamp}"
    suffix = 1
    while archive_dir.exists():
        archive_dir = RULES_DIR / f"archive-{stamp}-{suffix}"
        suffix += 1
    archive_dir.mkdir(parents=True, exist_ok=False)
    destination = archive_dir / rule.path.name
    shutil.move(str(rule.path), str(destination))
    print(f"Rule archived: {rule.number}")
    print(f"Archive: {destination}")


def remove_rule(rule_reference: str) -> None:
    """Backward-compatible CLI command; removal archives instead of deleting."""
    rule = _find_rule(rule_reference)
    print("\nArchive PDF Unlocker Rule\n=========================")
    print(f"Rule     : {rule.number}")
    print(f"Name     : {rule.name}")
    print(f"Priority : {rule.priority}")
    answer = input("Archive this rule? Enter=No: ").strip().lower()
    if answer not in {"y", "yes"}:
        print("Rule not archived.")
        return
    archive_rule(rule.number)


def list_rules(category: str | None = None, priority: str | None = None) -> None:
    rules = load_rules()
    if category:
        rules = [r for r in rules if r.category.casefold() == category.casefold()]
    if priority:
        normalized = priority.strip().upper()
        _priority_key(normalized)
        rules = [r for r in rules if r.priority == normalized]
    if not rules:
        print("No active rules found.")
        return
    print("PDF Unlocker Rules\n==================")
    print(f"{'RULE':<8} {'PRIORITY':<9} {'CATEGORY':<14} NAME")
    print("-" * 76)
    for rule in rules:
        print(f"{rule.number:<8} {rule.priority:<9} {rule.category:<14} {rule.name}")
    print(f"\nTotal active rules: {len(rules)}")


def show_rule(rule_reference: str) -> None:
    rule = _find_rule(rule_reference)
    print("PDF Unlocker Rule\n=================")
    print(f"Rule     : {rule.number}")
    print(f"Name     : {rule.name}")
    print(f"Category : {rule.category}")
    print(f"Priority : {rule.priority}")
    print(f"File     : {rule.path}")
    print("\nPattern / Password Combination\n-------------------------------")
    if rule.fields:
        registry = _field_index()
        labels = []
        for index, part in enumerate(rule.fields, 1):
            field = registry.get(part.field_id, {})
            label = field.get("label", "field unavailable")
            detail = part.mode if part.count is None else f"{part.mode} {part.count}"
            if part.mode == "full":
                explanation = "use the complete field value"
            elif part.mode == "first":
                explanation = f"use the first {part.count} character(s)"
            elif part.mode == "last":
                explanation = f"use the last {part.count} character(s)"
            else:
                explanation = f"slice mode: {part.mode}"
            print(f"{index}. Field {part.field_id}: {label}")
            print(f"   Slice: {detail} — {explanation}")
            labels.append(label)
        print("\nCombination order: " + " + ".join(labels))
    else:
        print("Legacy component-based rule:")
        for index, component in enumerate(rule.components, 1):
            print(f"{index}. {component}")
    meanings = {
        "raw": "keep the generated combination's letter case unchanged",
        "lower": "convert the generated combination to lowercase",
        "upper": "convert the generated combination to uppercase",
        "capitalize": "uppercase the first character and lowercase the rest",
    }
    cases = tuple(rule.cases or (rule.case,))
    print("\nTransform cases: " + ", ".join(cases))
    for case in cases:
        print(f"Meaning ({case}): " + meanings.get(case, case))
    print("\nHow this rule works:")
    print("- Each field supplies a value from the selected profile.")
    print("- Fields are combined in the order listed above.")
    print("- A missing field may make this rule inapplicable to a profile.")
