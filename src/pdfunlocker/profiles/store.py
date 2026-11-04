"""SQLite persistence and stable field/value identifiers for profile data."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import date, datetime, timezone

from pdfunlocker.paths import DATABASE_DIR
from pdfunlocker.profiles.registry import (
    BANK_FIRST, BANK_LAST, BANK_SUFFIXES, FIELD_ID_BY_KEY, bank_field_id,
    bank_field_key, field_id_for_key,
)

DB_PATH = DATABASE_DIR / "profiles.sqlite3"

# Legacy internal SQLite field numbers are retained for foreign-key compatibility.
# Public permanent IDs are defined in profiles.registry and are used by rules/UI.
# Values remain keyed by stable field keys, independent of either identifier.
BUILTIN_FIELDS = (
    (1, "FIRST_NAME", "First Name", False, "Personal", False),
    (2, "MOBILE", "Mobile", True, "Personal", False),
    (3, "LAST_NAME", "Last Name", False, "Personal", False),
    (4, "EMAIL", "Email", True, "Personal", False),
    (5, "PINCODE", "Pincode", True, "Personal", False),
    (6, "ACCOUNT_NUMBER", "Account Number", True, "Financial", False),
    (7, "CREDIT_CARD_NUMBER", "Credit Card Number", True, "Financial", False),
    (8, "CUSTOMER_ID", "Customer ID", True, "Identity", False),
    (9, "DOB", "Date of Birth (DDMMYYYY)", False, "Personal", False),
    (10, "BIRTH_MONTH", "Birth Month", False, "Personal", True),
    (11, "BIRTH_YEAR", "Birth Year", False, "Personal", True),
    (12, "MIDDLE_NAME", "Middle Name", False, "Personal", False),
    (13, "MOTHER_NAME", "Mother Name", False, "Personal", False),
    (14, "PAN", "PAN", False, "Identity", False),
    (15, "AADHAAR_FIRST4", "Aadhaar First 4", False, "Identity", False),
    (16, "AADHAAR_LAST4", "Aadhaar Last 4", False, "Identity", False),
    (17, "EMPLOYEE_ID", "Employee ID", True, "Identity", False),
    (18, "ROLL_NUMBER", "Roll Number", True, "Identity", False),
    (19, "IFSC", "IFSC", True, "Financial", False),
    (20, "CIF", "CIF", True, "Financial", False),
    (21, "ACCOUNT_TITLE", "Account Title", False, "Financial", True),
    (22, "UAN", "UAN", True, "Benefits & Retirement", False),
    (23, "PRAN", "PRAN", True, "Benefits & Retirement", False),
    (24, "POLICY_NUMBER", "Policy Number", True, "Benefits & Retirement", False),
    (25, "PPO_NUMBER", "PPO Number", True, "Benefits & Retirement", False),
    (26, "TAN", "TAN", True, "Tax & Business", False),
    (27, "GSTIN", "GSTIN", True, "Tax & Business", False),
    # Retained but archived; these IDs are not reused.
    (28, "INCORPORATION_DAY", "Incorporation Day", False, "Business", True),
    (29, "INCORPORATION_MONTH", "Incorporation Month", False, "Business", True),
    (30, "INCORPORATION_YEAR", "Incorporation Year", False, "Business", True),
    (31, "TITLE", "Title", False, "Personal", False),
    (32, "BIRTH_DAY", "Birth Day (legacy)", False, "Personal", True),
)
CATEGORY_ORDER = ("Personal", "Identity", "Financial", "Benefits & Retirement", "Tax & Business", "Custom", "Business")
_REPEATABLE_KEYS = {key for _n, key, _label, multiple, _category, archived in BUILTIN_FIELDS if multiple and not archived}
_REPEATABLE_SUFFIX = re.compile(r"^(.*)_(\d+)$")


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize() -> None:
    with _connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                legacy_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS field_definitions (
                field_number INTEGER PRIMARY KEY,
                field_id TEXT,
                field_key TEXT NOT NULL UNIQUE,
                label TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'Custom',
                allows_multiple INTEGER NOT NULL DEFAULT 0 CHECK(allows_multiple IN (0,1)),
                archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
                is_builtin INTEGER NOT NULL DEFAULT 0 CHECK(is_builtin IN (0,1)),
                is_custom INTEGER NOT NULL DEFAULT 0 CHECK(is_custom IN (0,1)),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profile_values (
                value_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
                field_key TEXT NOT NULL,
                value_sequence INTEGER NOT NULL DEFAULT 0,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id, field_key)
            );
            CREATE TABLE IF NOT EXISTS value_counters (
                profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
                field_number INTEGER NOT NULL REFERENCES field_definitions(field_number),
                next_sequence INTEGER NOT NULL,
                PRIMARY KEY(profile_id, field_number)
            );
            CREATE TABLE IF NOT EXISTS schema_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
        # Upgrade older installations without dropping profile values.
        columns = {row[1] for row in db.execute("PRAGMA table_info(field_definitions)")}
        if "category" not in columns:
            db.execute("ALTER TABLE field_definitions ADD COLUMN category TEXT NOT NULL DEFAULT 'Custom'")
        if "field_id" not in columns:
            db.execute("ALTER TABLE field_definitions ADD COLUMN field_id TEXT")
        version_row = db.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()
        version = str(version_row["value"]) if version_row else "0"
        existing = db.execute("SELECT COUNT(*) AS n FROM field_definitions").fetchone()["n"]
        now = _now()

        # Schema v2 used internal field_number 9 for BIRTH_DAY. Move that
        # legacy definition to internal slot 32 so DOB can retain slot 9; the
        # new public IDs are independent of these internal SQLite numbers.
        if version == "2" and existing:
            id_nine = db.execute(
                "SELECT field_key FROM field_definitions WHERE field_number=9"
            ).fetchone()
            if id_nine and id_nine["field_key"] not in {"BIRTH_DAY", "DOB"}:
                raise RuntimeError(
                    "Cannot migrate profile fields: internal field_number 9 is occupied by "
                    f"{id_nine['field_key']!r}, not BIRTH_DAY."
                )
            legacy_day = db.execute(
                "SELECT field_number FROM field_definitions WHERE field_key='BIRTH_DAY'"
            ).fetchone()
            existing_dob = db.execute(
                "SELECT field_number FROM field_definitions WHERE field_key='DOB'"
            ).fetchone()
            if legacy_day and int(legacy_day["field_number"]) == 9:
                if existing_dob:
                    raise RuntimeError(
                        "Cannot migrate profile fields: both DOB and BIRTH_DAY "
                        "are registered while BIRTH_DAY owns internal field_number 9."
                    )
                occupied_32 = db.execute(
                    "SELECT 1 FROM field_definitions WHERE field_number=32"
                ).fetchone()
                next_number = 32 if occupied_32 is None else int(
                    db.execute(
                        "SELECT COALESCE(MAX(field_number),0)+1 AS n "
                        "FROM field_definitions"
                    ).fetchone()["n"]
                )
                db.execute(
                    "UPDATE field_definitions SET field_number=? "
                    "WHERE field_key='BIRTH_DAY'",
                    (next_number,),
                )

        if version not in {"2", "3"} and existing:
            # This is the initial development registry, so normalize it once to the
            # agreed IDs while preserving profile values and their stable value IDs.
            db.execute("DELETE FROM value_counters")
            rows = [dict(row) for row in db.execute("SELECT * FROM field_definitions").fetchall()]
            for row in rows:
                db.execute("UPDATE field_definitions SET field_number=? WHERE field_key=?", (-int(row["field_number"]), row["field_key"]))
            used_keys = set()
            for number, key, label, multiple, category, archived in BUILTIN_FIELDS:
                row = next((item for item in rows if item["field_key"] == key), None)
                if row:
                    db.execute("UPDATE field_definitions SET field_number=?,label=?,category=?,allows_multiple=?,archived=?,is_builtin=1,is_custom=0 WHERE field_key=?",
                               (number, label, category, int(multiple), int(archived), key))
                else:
                    db.execute("INSERT INTO field_definitions(field_number,field_key,label,category,allows_multiple,archived,is_builtin,is_custom,created_at) VALUES(?,?,?,?,?,?,1,0,?)",
                               (number, key, label, category, int(multiple), int(archived), now))
                used_keys.add(key)
            next_number = max(item[0] for item in BUILTIN_FIELDS) + 1
            for row in rows:
                key = row["field_key"]
                if key in used_keys:
                    continue
                db.execute("UPDATE field_definitions SET field_number=?,category=COALESCE(NULLIF(category,''),'Custom') WHERE field_key=?",
                           (next_number, key))
                next_number += 1
            # Preserve all existing values while rebuilding monotonic sequence counters.
            for row in db.execute("SELECT profile_id,field_key,value_sequence FROM profile_values WHERE value_sequence>0").fetchall():
                key = str(row["field_key"])
                match = _REPEATABLE_SUFFIX.fullmatch(key)
                base = match.group(1) if match and int(match.group(2)) > 0 else key
                frow = db.execute("SELECT field_number FROM field_definitions WHERE field_key=?", (base,)).fetchone()
                if frow:
                    db.execute("INSERT INTO value_counters(profile_id,field_number,next_sequence) VALUES(?,?,?) ON CONFLICT(profile_id,field_number) DO UPDATE SET next_sequence=MAX(next_sequence,excluded.next_sequence)",
                               (row["profile_id"], frow["field_number"], int(row["value_sequence"])+1))
        else:
            for number, key, label, multiple, category, archived in BUILTIN_FIELDS:
                db.execute("INSERT OR IGNORE INTO field_definitions(field_number,field_key,label,category,allows_multiple,archived,is_builtin,is_custom,created_at) VALUES(?,?,?,?,?,?,1,0,?)",
                           (number, key, label, category, int(multiple), int(archived), now))
                db.execute("UPDATE field_definitions SET label=?,category=?,allows_multiple=?,archived=?,is_builtin=1,is_custom=0 WHERE field_key=?",
                           (label, category, int(multiple), int(archived), key))
        title_row = db.execute(
            "SELECT field_number FROM field_definitions WHERE field_key='TITLE'"
        ).fetchone()
        if title_row is None:
            title_number = int(
                db.execute(
                    "SELECT COALESCE(MAX(field_number),0)+1 AS n FROM field_definitions"
                ).fetchone()["n"]
            )
            db.execute(
                "INSERT INTO field_definitions"
                "(field_number,field_key,label,category,allows_multiple,archived,is_builtin,is_custom,created_at) "
                "VALUES(?, 'TITLE', 'Title', 'Personal', 0, 0, 1, 0, ?)",
                (title_number, now),
            )
        else:
            db.execute(
                "UPDATE field_definitions SET label='Title',category='Personal',"
                "allows_multiple=0,archived=0,is_builtin=1,is_custom=0 "
                "WHERE field_key='TITLE'"
            )

        # Convert valid legacy split birthday values into DOB once. Keep all
        # legacy values untouched for compatibility and auditability.
        current_year = date.today().year
        profile_ids = [
            int(row["profile_id"])
            for row in db.execute("SELECT profile_id FROM profiles").fetchall()
        ]
        for profile_id in profile_ids:
            legacy_values = {
                str(row["field_key"]): str(row["value"])
                for row in db.execute(
                    "SELECT field_key,value FROM profile_values WHERE profile_id=?",
                    (profile_id,),
                ).fetchall()
            }
            if legacy_values.get("DOB"):
                continue
            day = legacy_values.get("BIRTH_DAY", "")
            month = legacy_values.get("BIRTH_MONTH", "")
            year = legacy_values.get("BIRTH_YEAR", "")
            if not (
                re.fullmatch(r"[0-9]{1,2}", day)
                and re.fullmatch(r"[0-9]{1,2}", month)
                and re.fullmatch(r"[0-9]{4}", year)
            ):
                continue
            try:
                parsed = date(int(year), int(month), int(day))
            except ValueError:
                continue
            if not 1900 <= parsed.year <= current_year:
                continue
            dob_value = f"{parsed.day:02d}{parsed.month:02d}{parsed.year:04d}"
            db.execute(
                "INSERT INTO profile_values"
                "(profile_id,field_key,value_sequence,value,created_at,updated_at) "
                "VALUES(?, 'DOB', 0, ?, ?, ?) "
                "ON CONFLICT(profile_id,field_key) DO NOTHING",
                (profile_id, dob_value, now, now),
            )

        # Install the new public field registry without changing internal
        # SQLite field_number values or profile_values/value_counters keys.
        _install_public_registry(db, now)

        # Encrypt any legacy full card numbers already stored in profile_values.
        # Masked-only legacy values are retained because their full PAN is not recoverable.
        from pdfunlocker.profiles.card_crypto import encrypt_profile_value, is_card_field_key
        for card_row in db.execute(
            "SELECT value_id,field_key,value FROM profile_values"
        ).fetchall():
            field_key = str(card_row["field_key"])
            raw_value = str(card_row["value"])
            if not is_card_field_key(field_key):
                continue
            encrypted_value = encrypt_profile_value(field_key, raw_value)
            if encrypted_value != raw_value:
                db.execute(
                    "UPDATE profile_values SET value=?,updated_at=? WHERE value_id=?",
                    (encrypted_value, now, int(card_row["value_id"])),
                )

        db.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('schema_version','3')")
        db.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('field_registry_version','1')")
        try:
            DB_PATH.chmod(0o600)
        except OSError:
            pass


def _install_public_registry(db: sqlite3.Connection, now: str) -> None:
    """Assign permanent public IDs and install the new active fields."""
    new_fields = (
        ("AADHAAR", "Aadhaar Number", False, "Identity"),
        ("INCORPORATION_DATE", "Incorporation Date (DDMMYYYY)", False, "Business"),
    )
    for key, label, multiple, category in new_fields:
        row = db.execute("SELECT field_number FROM field_definitions WHERE field_key=?", (key,)).fetchone()
        if row is None:
            number = int(db.execute("SELECT COALESCE(MAX(field_number),0)+1 FROM field_definitions").fetchone()[0])
            db.execute(
                "INSERT INTO field_definitions(field_number,field_id,field_key,label,category,allows_multiple,archived,is_builtin,is_custom,created_at) "
                "VALUES(?,?,?,?,?,?,0,1,0,?)",
                (number, FIELD_ID_BY_KEY[key], key, label, category, int(multiple), now),
            )
        else:
            db.execute(
                "UPDATE field_definitions SET label=?,category=?,allows_multiple=?,archived=0,is_builtin=1,is_custom=0 WHERE field_key=?",
                (label, category, int(multiple), key),
            )

    # Legacy split Aadhaar fields and superseded account-level fields remain
    # in the registry as archived definitions; their values remain auditable.
    archived_keys = (
        "AADHAAR_FIRST4", "AADHAAR_LAST4", "ACCOUNT_NUMBER",
        "CREDIT_CARD_NUMBER", "CUSTOMER_ID", "IFSC", "CIF",
        "ACCOUNT_TITLE", "ROLL_NUMBER", "BIRTH_DAY", "BIRTH_MONTH",
        "BIRTH_YEAR", "INCORPORATION_DAY", "INCORPORATION_MONTH",
        "INCORPORATION_YEAR",
    )
    db.execute("UPDATE field_definitions SET allows_multiple=1 WHERE field_key='PINCODE'")
    db.execute(
        "UPDATE field_definitions SET archived=1 WHERE field_key IN ("
        + ",".join("?" for _ in archived_keys) + ")",
        archived_keys,
    )

    # Ensure the first bank group exists. Additional groups are allocated by
    # ensure_bank_group() when a user adds another bank to a profile.
    _ensure_bank_group_db(db, BANK_FIRST, now)

    rows = db.execute("SELECT field_number,field_key,is_custom FROM field_definitions").fetchall()
    for row in rows:
        number = int(row["field_number"])
        key = str(row["field_key"])
        public_id = field_id_for_key(key, number, is_custom=bool(row["is_custom"]))
        db.execute("UPDATE field_definitions SET field_id=? WHERE field_number=?", (public_id, number))

    # A unique index makes accidental ID reuse fail immediately.
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_field_definitions_field_id ON field_definitions(field_id)")


def _ensure_bank_group_db(db: sqlite3.Connection, group: int, now: str) -> list[dict]:
    if not BANK_FIRST <= int(group) <= BANK_LAST:
        raise ValueError("Bank group must be between 1200 and 1699")
    created = []
    for suffix, (_base_key, label, multiple) in BANK_SUFFIXES.items():
        key = bank_field_key(group, suffix)
        public_id = bank_field_id(group, suffix)
        row = db.execute("SELECT field_number FROM field_definitions WHERE field_id=? OR field_key=?", (public_id, key)).fetchone()
        if row is None:
            number = int(db.execute("SELECT COALESCE(MAX(field_number),0)+1 FROM field_definitions").fetchone()[0])
            display = f"Bank {group - BANK_FIRST + 1:02d} {label}"
            db.execute(
                "INSERT INTO field_definitions(field_number,field_id,field_key,label,category,allows_multiple,archived,is_builtin,is_custom,created_at) "
                "VALUES(?,?,?,?, 'Banking', ?,0,1,0,?)",
                (number, public_id, key, display, int(multiple), now),
            )
        else:
            db.execute("UPDATE field_definitions SET field_id=?,archived=0,allows_multiple=?,category='Banking',is_builtin=1,is_custom=0 WHERE field_number=?", (public_id, int(multiple), int(row["field_number"])))
        created.append({"field_id": public_id, "field_key": key, "label": label, "allows_multiple": multiple})
    return created


def ensure_bank_group(group: int) -> list[dict]:
    """Create or return the six permanent field definitions for one bank."""
    initialize()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        return _ensure_bank_group_db(db, int(group), _now())


def next_bank_group() -> int | None:
    initialize()
    with _connect() as db:
        row = db.execute(
            "SELECT MAX(CAST(substr(field_id,1,4) AS INTEGER)) AS highest "
            "FROM field_definitions WHERE field_id GLOB '1[2-6][0-9][0-9]A'"
        ).fetchone()
        highest = int(row["highest"] or (BANK_FIRST - 1))
        candidate = max(BANK_FIRST, highest + 1)
        return candidate if candidate <= BANK_LAST else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_field_key(key: str) -> tuple[str, int]:
    """Map repeatable keys such as MOBILE_02 or a custom field's _02 value."""
    match = _REPEATABLE_SUFFIX.fullmatch(key)
    if not match:
        return key, 0
    base, suffix = match.group(1), int(match.group(2))
    if base in _REPEATABLE_KEYS:
        return base, suffix
    if DB_PATH.exists():
        try:
            with _connect() as db:
                row = db.execute("SELECT allows_multiple FROM field_definitions WHERE field_key=?", (base,)).fetchone()
                if row and row["allows_multiple"]:
                    return base, suffix
        except sqlite3.Error:
            pass
    return key, 0


def ensure_field(field_key: str, label: str | None = None, allows_multiple: bool | None = None, category: str = "Custom") -> int:
    initialize()
    base, _seq = split_field_key(field_key)
    if allows_multiple is None:
        allows_multiple = base in _REPEATABLE_KEYS
    if label is None:
        label = base.replace("_", " ").title()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT field_number FROM field_definitions WHERE field_key=?", (base,)).fetchone()
        if row:
            return int(row["field_number"])
        number = int(db.execute("SELECT COALESCE(MAX(field_number),0)+1 AS n FROM field_definitions").fetchone()["n"])
        public_id = f"CUSTOM{number:04d}"
        db.execute(
            "INSERT INTO field_definitions(field_number,field_id,field_key,label,category,allows_multiple,is_builtin,created_at) VALUES(?,?,?,?,?,?,0,?)",
            (number, public_id, base, label, category, int(allows_multiple), _now()),
        )
        return number


def add_field(
    label: str,
    field_key: str,
    allows_multiple: bool = False,
    category: str | None = None,
) -> tuple[int, str]:
    label = label.strip()
    field_key = re.sub(r"[^A-Z0-9_]+", "_", field_key.strip().upper()).strip("_")
    if not label or not field_key or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", field_key):
        raise ValueError("Field label and a valid field key are required.")
    if re.search(r"_\d+$", field_key):
        raise ValueError("Field key must not end in a numeric suffix.")

    requested_category = category
    effective_category = category if category is not None else "Custom"
    number = ensure_field(field_key, label, allows_multiple, effective_category)
    with _connect() as db:
        row = db.execute(
            "SELECT label,allows_multiple,is_custom,is_builtin,category "
            "FROM field_definitions WHERE field_number=?",
            (number,),
        ).fetchone()
        if (
            row["label"] != label
            or bool(row["allows_multiple"]) != bool(allows_multiple)
            or (requested_category is not None and not row["is_builtin"] and row["category"] != requested_category)
        ):
            # Existing definitions are immutable here; changing them needs an explicit modify workflow.
            public_id = row["field_id"] if "field_id" in row.keys() else f"{number:03d}"
            raise ValueError(f"Field already exists as ID {public_id}; existing definition was kept.")
        db.execute("UPDATE field_definitions SET is_custom=1 WHERE field_number=? AND is_builtin=0", (number,))
    return number, field_key


def list_fields(include_archived: bool = False) -> list[dict]:
    initialize()
    query = "SELECT * FROM field_definitions" + ("" if include_archived else " WHERE archived=0") + " ORDER BY field_id COLLATE BINARY, field_number"
    with _connect() as db:
        return [dict(row) for row in db.execute(query).fetchall()]


def archive_field(field_key: str) -> None:
    initialize()
    with _connect() as db:
        row = db.execute("SELECT is_builtin FROM field_definitions WHERE field_key=?", (field_key.upper(),)).fetchone()
        if not row:
            raise ValueError(f"Unknown field: {field_key}")
        if row["is_builtin"]:
            raise ValueError("Built-in fields cannot be archived.")
        db.execute("UPDATE field_definitions SET archived=1 WHERE field_key=?", (field_key.upper(),))


def save_profile(path: Path, values: dict[str, str]) -> None:
    initialize()
    pid_text = str(values.get("PROFILE_ID", "")).strip()
    name = str(values.get("PROFILE_NAME", "")).strip()
    if not pid_text.isdigit() or not name:
        return
    pid = int(pid_text)
    now = _now()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO profiles(profile_id,name,legacy_path,created_at,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(profile_id) DO UPDATE SET name=excluded.name,legacy_path=excluded.legacy_path,updated_at=excluded.updated_at",
            (pid, name, str(path), now, now),
        )
        from pdfunlocker.profiles.card_crypto import encrypt_profile_value
        for key, value in values.items():
            if key in {"PROFILE_ID", "PROFILE_NAME"}:
                continue
            base, seq = split_field_key(key)
            persisted_value = encrypt_profile_value(base, str(value))
            # Legacy repeatable values share one field definition and retain their old keys for rule compatibility.
            field_row = db.execute("SELECT field_number FROM field_definitions WHERE field_key=?", (base,)).fetchone()
            if not field_row:
                number = int(db.execute("SELECT COALESCE(MAX(field_number),0)+1 AS n FROM field_definitions").fetchone()["n"])
                multi = int(seq > 0)
                db.execute(
                    "INSERT INTO field_definitions(field_number,field_id,field_key,label,category,allows_multiple,is_builtin,created_at) VALUES(?,?,?,?,?,?,0,?)",
                    (number, f"CUSTOM{number:04d}", base, base.replace("_", " ").title(), "Custom", multi, now),
                )
                field_number = number
            else:
                field_number = int(field_row["field_number"])
            db.execute(
                "INSERT INTO profile_values(profile_id,field_key,value_sequence,value,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(profile_id,field_key) DO UPDATE SET value_sequence=excluded.value_sequence,value=excluded.value,updated_at=excluded.updated_at",
                (pid, key, seq, persisted_value, now, now),
            )
            if seq > 0:
                db.execute(
                    "INSERT INTO value_counters(profile_id,field_number,next_sequence) VALUES(?,?,?) "
                    "ON CONFLICT(profile_id,field_number) DO UPDATE SET next_sequence=MAX(next_sequence,excluded.next_sequence)",
                    (pid, field_number, seq + 1),
                )
        # Remove DB values absent from the current dictionary, but keep field definitions and counters.
        current = [k for k in values if k not in {"PROFILE_ID", "PROFILE_NAME"}]
        if current:
            marks = ",".join("?" for _ in current)
            db.execute(f"DELETE FROM profile_values WHERE profile_id=? AND field_key NOT IN ({marks})", (pid, *current))
        else:
            db.execute("DELETE FROM profile_values WHERE profile_id=?", (pid,))


def load_profile(profile_id: int) -> dict[str, str] | None:
    initialize()
    with _connect() as db:
        profile = db.execute("SELECT profile_id,name FROM profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if not profile:
            return None
        result = {"PROFILE_ID": str(profile["profile_id"]), "PROFILE_NAME": str(profile["name"])}
        for row in db.execute("SELECT field_key,value FROM profile_values WHERE profile_id=? ORDER BY value_id", (profile_id,)):
            result[str(row["field_key"])] = str(row["value"])
        return result


def reserve_profile_id(sequence_hint: int = 0) -> int:
    """Atomically reserve a monotonically increasing profile ID."""
    initialize()
    hint = max(0, int(sequence_hint))
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT COALESCE(MAX(profile_id), 0) AS highest FROM profiles"
        ).fetchone()
        highest = int(row["highest"])
        row = db.execute(
            "SELECT value FROM schema_metadata "
            "WHERE key='profile_id_high_water_mark'"
        ).fetchone()
        try:
            high_water = int(row["value"]) if row else 0
        except (TypeError, ValueError):
            high_water = 0
        allocated = max(hint, highest, high_water, 0) + 1
        db.execute(
            "INSERT INTO schema_metadata(key,value) "
            "VALUES('profile_id_high_water_mark', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(allocated),),
        )
        return allocated


def list_profiles() -> list[dict[str, str]]:
    """Return profile records from SQLite; exports are not authoritative."""
    initialize()
    with _connect() as db:
        rows = db.execute(
            "SELECT profile_id, name, legacy_path "
            "FROM profiles ORDER BY profile_id"
        ).fetchall()
        return [
            {
                "profile_id": str(row["profile_id"]),
                "name": str(row["name"]),
                "legacy_path": str(row["legacy_path"] or ""),
            }
            for row in rows
        ]

def delete_profile(profile_id: int) -> None:
    initialize()
    with _connect() as db:
        db.execute("DELETE FROM profiles WHERE profile_id=?", (profile_id,))


def next_value_sequence(
    profile_id: int,
    field_key: str,
    current_values: dict[str, str] | None = None,
) -> int:
    """Return the next never-reused sequence for a repeatable profile field."""
    initialize()
    highest = 0
    if current_values:
        for key in current_values:
            if key == field_key:
                highest = max(highest, 1)
            else:
                base, sequence = split_field_key(key)
                if base == field_key and sequence > 0:
                    highest = max(highest, sequence)

    with _connect() as db:
        field = db.execute(
            "SELECT field_number FROM field_definitions WHERE field_key=?",
            (field_key,),
        ).fetchone()
        if field is None:
            return highest + 1

        counter = db.execute(
            "SELECT next_sequence FROM value_counters "
            "WHERE profile_id=? AND field_number=?",
            (int(profile_id), int(field["field_number"])),
        ).fetchone()
        next_saved = int(counter["next_sequence"]) if counter else 1

        rows = db.execute(
            "SELECT field_key, value_sequence FROM profile_values WHERE profile_id=?",
            (int(profile_id),),
        ).fetchall()
        for row in rows:
            key = str(row["field_key"])
            if key == field_key:
                highest = max(highest, 1)
            else:
                base, sequence = split_field_key(key)
                if base == field_key and sequence > 0:
                    highest = max(highest, sequence)

    return max(next_saved, highest + 1)


def _alpha_suffix(sequence: int) -> str:
    if sequence < 1:
        return ""
    out = ""
    while sequence:
        sequence, remainder = divmod(sequence - 1, 26)
        out = chr(65 + remainder) + out
    return out


def value_code(field_number: int | str, sequence: int = 0, allows_multiple: bool = False) -> str:
    """Render the permanent public ID, adding a value sequence when needed."""
    if isinstance(field_number, int):
        initialize()
        with _connect() as db:
            row = db.execute("SELECT field_id FROM field_definitions WHERE field_number=?", (field_number,)).fetchone()
        base = str(row["field_id"]) if row and row["field_id"] else f"LEGACY-{field_number:04d}"
    else:
        base = str(field_number)
    return f"{base}-{sequence:02d}" if allows_multiple and sequence > 0 else base
