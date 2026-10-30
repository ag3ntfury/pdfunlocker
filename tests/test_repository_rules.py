from pathlib import Path

from pdfunlocker.rules.manager import _parse_rule


RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


def rule_signature(rule):
    """Return the candidate-generation pattern, excluding rule metadata."""
    if rule.fields:
        pattern = (
            "fields",
            tuple(
                (part.field_id, part.mode, part.count)
                for part in rule.fields
            ),
        )
    else:
        pattern = ("components", tuple(rule.components))

    cases = tuple(sorted(set(rule.cases or (rule.case,))))
    return pattern, cases


def test_all_repository_rules_parse():
    files = sorted(RULES_DIR.glob("rule*.yml"))
    assert files, f"No rule YAML files found in {RULES_DIR}"

    errors = []
    for path in files:
        try:
            _parse_rule(path)
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    assert not errors, "Invalid rules:\n" + "\n".join(errors)


def test_rule_numbers_and_ids_are_unique():
    rules = [
        _parse_rule(path)
        for path in sorted(RULES_DIR.glob("rule*.yml"))
    ]

    numbers = [rule.number for rule in rules]
    ids = [rule.rule_id.casefold() for rule in rules]

    assert len(numbers) == len(set(numbers)), "Duplicate rule number found"
    assert len(ids) == len(set(ids)), "Duplicate rule ID found"


def test_candidate_generation_patterns_are_unique():
    rules = [
        _parse_rule(path)
        for path in sorted(RULES_DIR.glob("rule*.yml"))
    ]

    seen = {}
    duplicates = []

    for rule in rules:
        signature = rule_signature(rule)
        if signature in seen:
            duplicates.append(
                f"{seen[signature]} and {rule.path.name}"
            )
        else:
            seen[signature] = rule.path.name

    assert not duplicates, (
        "Duplicate candidate-generation patterns found:\n"
        + "\n".join(duplicates)
    )
