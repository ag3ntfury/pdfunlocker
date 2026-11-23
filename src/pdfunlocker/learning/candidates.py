"""Secure PDF password candidate generation from profile values and YAML rules.

Plaintext candidates are returned only in memory. They are never written
to files, SQLite, logs, or terminal output.
"""

import hashlib
import hmac
import itertools
import os
import secrets
import stat
from pathlib import Path

import yaml

from pdfunlocker.learning.database import initialize_learning_database
from pdfunlocker.profiles.store import (
    get_profile,
    load_field_registry,
)


ALLOWED_TRANSFORMS = {"lower", "upper", "raw"}
KEY_SIZE = 32
MAX_CANDIDATES_PER_RULE = 10_000


class CandidateLimitExceeded(ValueError):
    """Raised when a rule produces more than the configured unique candidates."""

    def __init__(self, limit=MAX_CANDIDATES_PER_RULE):
        self.limit = limit
        super().__init__(f"Rule exceeds the maximum of {limit:,} unique candidates.")


def _required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string.")
    return value.strip()


def _load_hmac_key(key_path):
    """Load or securely create a separate installation HMAC key."""

    path = Path(key_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)

    try:
        descriptor = os.open(flags=flags, path=str(path), mode=0o600)
    except FileExistsError:
        pass
    else:
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(secrets.token_bytes(KEY_SIZE))
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                path.unlink()
            except OSError:
                pass
            raise

    if path.is_symlink():
        raise ValueError("HMAC key path must not be a symbolic link.")

    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValueError("Unable to inspect HMAC key file.") from exc

    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("HMAC key must be a regular file.")

    try:
        os.chmod(path, 0o600)
        key = path.read_bytes()
    except OSError as exc:
        raise ValueError("Unable to read or protect HMAC key.") from exc

    if len(key) != KEY_SIZE:
        raise ValueError("HMAC key has an invalid length.")

    return key


def _load_rule(rules_directory, rule_id):
    directory = Path(rules_directory).expanduser()

    if not directory.is_dir():
        raise FileNotFoundError(
            f"Rules directory not found: {directory}"
        )

    if len(rule_id) != 5 or not rule_id.isdigit():
        raise ValueError("Rule ID must contain five digits.")

    path = directory / f"rule{rule_id}.yml"

    if not path.is_file():
        raise FileNotFoundError(f"Rule not found: {rule_id}")

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid rule file: {path}")

    rule = data.get("rule")
    if not isinstance(rule, dict):
        raise ValueError(f"Missing rule metadata: {path}")

    if str(rule.get("id", "")) != rule_id:
        raise ValueError("Rule ID does not match its filename.")

    if data.get("status") != "active":
        raise ValueError(f"Rule {rule_id} is inactive.")

    return data


def _validate_rule(rule_data, field_registry):
    pattern = rule_data.get("pattern")
    if not isinstance(pattern, dict):
        raise ValueError("Rule pattern must be a mapping.")

    fields = pattern.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("Rule must contain at least one pattern field.")

    validated_fields = []

    for item in fields:
        if not isinstance(item, dict):
            raise ValueError("Invalid pattern field.")

        field_id = item.get("field_id")
        if not isinstance(field_id, str):
            raise ValueError("Pattern field ID must be a string.")

        if field_id not in field_registry:
            raise ValueError(f"Unknown profile field ID: {field_id}")

        slicing = item.get("slice")
        if not isinstance(slicing, dict):
            raise ValueError(f"Missing slice configuration: {field_id}")

        mode = slicing.get("mode")

        if mode not in {"first", "last", "full"}:
            raise ValueError(f"Invalid slice mode: {field_id}")

        count = slicing.get("count")

        if mode in {"first", "last"}:
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count < 1
            ):
                raise ValueError(
                    f"Slice count must be a positive integer: {field_id}"
                )
        elif count is not None:
            raise ValueError(
                f"Full slice must not specify a count: {field_id}"
            )

        validated_fields.append({
            "field_id": field_id,
            "mode": mode,
            "count": count,
        })

    transform = rule_data.get("transform")
    if not isinstance(transform, dict):
        raise ValueError("Rule transformation must be a mapping.")

    cases = transform.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Rule must contain transformation cases.")

    if any(case not in ALLOWED_TRANSFORMS for case in cases):
        raise ValueError("Rule contains an unsupported transformation.")

    if len(cases) != len(set(cases)):
        raise ValueError("Duplicate transformation cases are not allowed.")

    return validated_fields, cases


def _slice_value(value, mode, count):
    if mode == "first":
        return value[:count]

    if mode == "last":
        return value[-count:]

    return value


def _transform(value, case):
    if case == "lower":
        return value.lower()

    if case == "upper":
        return value.upper()

    return value


def _candidate_fingerprint(key, candidate):
    message = b"pdfunlocker-candidate-v1\0" + candidate.encode("utf-8")

    return hmac.new(
        key,
        message,
        hashlib.sha256,
    ).hexdigest()


def generate_candidates(
    database_path,
    template_path,
    rules_directory,
    profile_id,
    rule_id,
    key_path=None,
):
    """
    Generate ordered, deduplicated candidates for one profile and rule.

    Multiple-value fields are combined using deterministic Cartesian
    combinations in profile value order and YAML field order.

    The returned candidate values exist only in memory.
    """

    rule_id = _required_text(rule_id, "rule_id")
    profile_id = _required_text(str(profile_id), "profile_id")

    initialize_learning_database(database_path)

    if key_path is None:
        key_path = (
            Path(database_path).expanduser().parent
            / "candidate_hmac.key"
        )

    key = _load_hmac_key(key_path)

    field_registry = load_field_registry(template_path)
    rule_data = _load_rule(rules_directory, rule_id)

    pattern_fields, transformations = _validate_rule(
        rule_data, field_registry
    )

    profile, stored_values = get_profile(
        database_path, profile_id
    )

    if not profile["enabled"]:
        raise ValueError("Profile is disabled.")

    values_by_field = {}

    for row in stored_values:
        values_by_field.setdefault(row["field_id"], []).append(
            row["value"]
        )

    field_options = []

    for item in pattern_fields:
        field_id = item["field_id"]
        field_definition = field_registry[field_id]

        values = values_by_field.get(field_id, [])

        if not values:
            return {
                "profile_id": profile_id,
                "rule_id": rule_id,
                "candidate_set_fingerprint": hmac.new(
                    key,
                    b"pdfunlocker-candidate-set-v1\0empty",
                    hashlib.sha256,
                ).hexdigest(),
                "count": 0,
                "candidates": [],
            }

        if field_definition["multiplicity"] == "S" and len(values) != 1:
            raise ValueError(
                f"Single-value field has unexpected values: {field_id}"
            )

        options = [
            _slice_value(
                str(value),
                item["mode"],
                item["count"],
            )
            for value in values
        ]

        field_options.append(options)

    unique_candidates = []
    seen = set()

    for combination in itertools.product(*field_options):
        base = "".join(combination)

        for transformation in transformations:
            candidate = _transform(base, transformation)

            if not candidate or candidate in seen:
                continue

            seen.add(candidate)
            unique_candidates.append(candidate)

            if len(unique_candidates) > MAX_CANDIDATES_PER_RULE:
                # Reject the complete rule; never return or execute a partial set.
                raise CandidateLimitExceeded()

    candidate_records = []

    for number, candidate in enumerate(unique_candidates, start=1):
        candidate_records.append({
            "number": number,
            "value": candidate,
            "fingerprint": _candidate_fingerprint(key, candidate),
        })

    set_message = (
        b"pdfunlocker-candidate-set-v1\0"
        + b"\0".join(
            record["fingerprint"].encode("ascii")
            for record in candidate_records
        )
    )

    set_fingerprint = hmac.new(
        key,
        set_message,
        hashlib.sha256,
    ).hexdigest()

    return {
        "profile_id": profile_id,
        "rule_id": rule_id,
        "candidate_set_fingerprint": set_fingerprint,
        "count": len(candidate_records),
        "candidates": candidate_records,
    }
