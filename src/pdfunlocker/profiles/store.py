"""SQLite persistence and stable field/value identifiers for profile data."""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import date, datetime, timezone

from pdfunlocker.paths import DATABASE_DIR
from pdfunlocker.profiles.locking import profile_store_lock
from pdfunlocker.profiles.registry import (
    BANK_FIRST, BANK_LAST, BANK_SUFFIXES, bank_field_id,
    bank_field_key, field_id_for_key, allocate_field_id, FIELD_CATEGORY_BY_KEY,
    FIELD_ID_BY_KEY, field_category_for_key, BANK_SUFFIX_BY_FIELD_KEY,
    normalize_field_category,
)

DB_PATH = DATABASE_DIR / "profiles.sqlite3"

# Legacy internal SQLite field numbers are retained for foreign-key compatibility.
# Public permanent IDs are defined in profiles.registry and are used by rules/UI.
# Values retain stable internal keys; their permanent public value IDs are stored separately.
BUILTIN_FIELDS = (
    (1, "FIRST_NAME", "First Name", False, "Personal", False),
    (2, "MOBILE", "Mobile", True, "Personal", False),
    (3, "LAST_NAME", "Last Name", False, "Personal", False),
    (4, "EMAIL", "Email", True, "Personal", False),
    (5, "PINCODE", "Pincode", True, "Personal", False),
    (6, "ACCOUNT_NUMBER", "Account Number", True, "Banking", True),
    (7, "CREDIT_CARD_NUMBER", "Credit Card Number", True, "Banking", True),
    (8, "CUSTOMER_ID", "Customer ID", True, "Banking", True),
    (9, "DOB", "Date of Birth (DDMMYYYY)", False, "Personal", False),
    (10, "BIRTH_MONTH", "Birth Month", False, "Personal", True),
    (11, "BIRTH_YEAR", "Birth Year", False, "Personal", True),
    (12, "MIDDLE_NAME", "Middle Name", False, "Personal", False),
    (13, "MOTHER_NAME", "Mother Name", False, "Personal", False),
    (14, "PAN", "PAN", False, "Private", False),
    (15, "AADHAAR_FIRST4", "Aadhaar First 4", False, "Private", True),
    (16, "AADHAAR_LAST4", "Aadhaar Last 4", False, "Private", True),
    (17, "EMPLOYEE_ID", "Employee ID", True, "Employment", False),
    (18, "ROLL_NUMBER", "Roll Number", True, "Education", False),
    (19, "IFSC", "IFSC", True, "Banking", True),
    (20, "CIF", "CIF", True, "Banking", True),
    (21, "ACCOUNT_TITLE", "Account Title", False, "Banking", True),
    (22, "UAN", "UAN", True, "Employment", False),
    (23, "PRAN", "PRAN", True, "Employment", False),
    (24, "POLICY_NUMBER", "Policy Number", True, "Insurance", False),
    (25, "PPO_NUMBER", "PPO Number", True, "Employment", False),
    (26, "TAN", "TAN", True, "Business", False),
    (27, "GSTIN", "GSTIN", True, "Business", False),
    # Retained but archived; these IDs are not reused.
    (28, "INCORPORATION_DAY", "Incorporation Day", False, "Business", True),
    (29, "INCORPORATION_MONTH", "Incorporation Month", False, "Business", True),
    (30, "INCORPORATION_YEAR", "Incorporation Year", False, "Business", True),
    (31, "TITLE", "Title", False, "Personal", False),
    (32, "BIRTH_DAY", "Birth Day (legacy)", False, "Personal", True),
    (33, "BUSINESS_NAME", "Business Name", True, "Business", False),
    (34, "BUSINESS_REGISTRATION_NUMBER", "Business Registration Number", True, "Business", False),
    (35, "INSURER_NAME", "Insurer Name", True, "Insurance", False),
    (36, "POLICY_TYPE", "Policy Type", True, "Insurance", False),
    (37, "INSTITUTION_NAME", "Institution Name", True, "Education", False),
    (38, "QUALIFICATION", "Qualification", True, "Education", False),
    (39, "COURSE", "Course", True, "Education", False),
    (40, "ENROLLMENT_NUMBER", "Enrollment Number", True, "Education", False),
    (41, "REGISTRATION_NUMBER", "Registration Number", True, "Education", False),
    (42, "BRANCH", "Bank Branch", True, "Banking", False),
    (43, "ACCOUNT_TYPE", "Account Type", True, "Banking", False),
)
CATEGORY_ORDER = ("Personal", "Private", "Banking", "Business", "Employment", "Insurance", "Education")
_REPEATABLE_KEYS = {key for _n, key, _label, multiple, _category, archived in BUILTIN_FIELDS if multiple and not archived}
_REPEATABLE_SUFFIX = re.compile(r"^(.*)_(\d+)$")


@contextmanager
def _connect():
    with profile_store_lock(DB_PATH):
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
            CREATE TABLE IF NOT EXISTS profile_banks (
                bank_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
                bank_sequence INTEGER NOT NULL,
                group_code INTEGER NOT NULL,
                bank_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id, bank_sequence),
                UNIQUE(profile_id, group_code)
            );
            CREATE TABLE IF NOT EXISTS profile_values (
                value_id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
                bank_id INTEGER REFERENCES profile_banks(bank_id) ON DELETE SET NULL,
                value_instance_id TEXT,
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
        value_columns = {row[1] for row in db.execute("PRAGMA table_info(profile_values)")}
        missing_bank_id = "bank_id" not in value_columns
        missing_value_instance_id = "value_instance_id" not in value_columns
        if missing_bank_id:
            db.execute("ALTER TABLE profile_values ADD COLUMN bank_id INTEGER REFERENCES profile_banks(bank_id) ON DELETE SET NULL")
        if missing_value_instance_id:
            db.execute("ALTER TABLE profile_values ADD COLUMN value_instance_id TEXT")
        version_row = db.execute("SELECT value FROM schema_metadata WHERE key='schema_version'").fetchone()
        version = str(version_row["value"]) if version_row else "0"
        needs_bank_migration = version != "4" or missing_bank_id
        missing_instance_rows = db.execute(
            "SELECT COUNT(*) FROM profile_values WHERE value_instance_id IS NULL"
        ).fetchone()[0]
        needs_instance_migration = version != "4" or missing_value_instance_id or bool(missing_instance_rows) or needs_bank_migration
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

        if version not in {"2", "3", "4"} and existing:
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
        if needs_bank_migration:
            _migrate_bank_ownership(db, now)
        if needs_instance_migration or db.execute(
            "SELECT 1 FROM profile_values WHERE value_instance_id IS NULL LIMIT 1"
        ).fetchone():
            _migrate_value_instance_ids(db, now)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_values_instance_id ON profile_values(profile_id,value_instance_id) WHERE value_instance_id IS NOT NULL")

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

        db.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('schema_version','4')")
        db.execute("INSERT OR REPLACE INTO schema_metadata(key,value) VALUES('field_registry_version','2')")
        try:
            DB_PATH.chmod(0o600)
        except OSError:
            pass


def _install_public_registry(db: sqlite3.Connection, now: str) -> None:
    """Assign permanent public IDs and install the new active fields."""
    # A field ID identifies a type, so multiple bank-group definitions may
    # intentionally share the same public ID. Drop the old uniqueness index
    # before assigning the shared IDs during this migration.
    db.execute("DROP INDEX IF EXISTS idx_field_definitions_field_id")
    new_fields = (
        ("AADHAAR", "Aadhaar Number", False, "Private"),
        ("INCORPORATION_DATE", "Incorporation Date (DDMMYYYY)", False, "Business"),
        ("BUSINESS_NAME", "Business Name", True, "Business"),
        ("BUSINESS_REGISTRATION_NUMBER", "Business Registration Number", True, "Business"),
        ("INSURER_NAME", "Insurer Name", True, "Insurance"),
        ("POLICY_TYPE", "Policy Type", True, "Insurance"),
        ("INSTITUTION_NAME", "Institution Name", True, "Education"),
        ("QUALIFICATION", "Qualification", True, "Education"),
        ("COURSE", "Course", True, "Education"),
        ("ENROLLMENT_NUMBER", "Enrollment Number", True, "Education"),
        ("REGISTRATION_NUMBER", "Registration Number", True, "Education"),
        ("BRANCH", "Bank Branch", True, "Banking"),
        ("ACCOUNT_TYPE", "Account Type", True, "Banking"),
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
        "ACCOUNT_TITLE", "BIRTH_DAY", "BIRTH_MONTH",
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

    rows = db.execute("SELECT field_number,field_id,field_key,is_custom,category FROM field_definitions").fetchall()
    used_numeric_ids = {
        str(row["field_id"]) for row in rows
        if str(row["field_id"] or "").isdigit()
    }
    used_numeric_ids.update(FIELD_ID_BY_KEY.values())
    for row in rows:
        number = int(row["field_number"])
        key = str(row["field_key"])
        if row["is_custom"]:
            # Keep valid, already-published numeric IDs. Upgrade intermediate
            # CUSTOM#### IDs when the legacy row has a real category; rows that
            # were genuinely uncategorized remain explicitly legacy until the
            # user assigns a category through a future migration workflow.
            old_id = str(row["field_id"] or "")
            try:
                custom_category = normalize_field_category(str(row["category"] or ""), allow_legacy=True)
            except ValueError:
                custom_category = "Custom"
            category_range = {
                "Personal": (1001, 3000), "Private": (3001, 4000),
                "Banking": (4001, 6000), "Business": (6001, 7000),
                "Employment": (7001, 8000), "Insurance": (8001, 9000),
                "Education": (9001, 10000),
            }.get(custom_category)
            old_numeric = int(old_id) if old_id.isdigit() else None
            if category_range and old_numeric and category_range[0] <= old_numeric <= category_range[1]:
                public_id = old_id
            elif category_range:
                public_id = allocate_field_id(custom_category, used_numeric_ids)
                used_numeric_ids.add(public_id)
            else:
                public_id = old_id or f"CUSTOM{number:04d}"
        else:
            public_id = field_id_for_key(key, number, is_custom=False)
        category_key = field_category_for_key(key)
        category = category_key.title().replace("_", " ") if category_key in FIELD_CATEGORY_BY_KEY.values() or category_key == "BANKING" else None
        if row["is_custom"]:
            custom_category = normalize_field_category(str(row["category"] or ""), allow_legacy=True)
            db.execute(
                "UPDATE field_definitions SET field_id=?,category=? WHERE field_number=?",
                (public_id, custom_category, number),
            )
        elif category:
            db.execute("UPDATE field_definitions SET field_id=?,category=? WHERE field_number=?", (public_id, category, number))
        else:
            db.execute("UPDATE field_definitions SET field_id=? WHERE field_number=?", (public_id, number))

    # Several bank-group field definitions share one field-type ID by design.
    # Uniqueness is enforced by the central registry, not per bank instance.



def _migrate_bank_ownership(db: sqlite3.Connection, now: str) -> None:
    """Backfill bank records and normalize legacy per-bank value sequences."""
    rows = db.execute(
        "SELECT profile_id, value_id, field_key, value_sequence, value "
        "FROM profile_values WHERE field_key GLOB 'BANK_1[2-6][0-9][0-9][A-F]*'"
    ).fetchall()
    groups: dict[tuple[int, int], str] = {}
    for row in rows:
        match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})A(?:_(\d+))?", str(row["field_key"]))
        if match:
            token = (int(row["profile_id"]), int(match.group(1)))
            if token not in groups or int(match.group(2) or "0") < 1:
                groups[token] = str(row["value"])
    # Include groups that have other bank values even if their name is blank.
    for row in rows:
        match = re.match(r"BANK_(1[2-6][0-9]{2})[A-F]", str(row["field_key"]))
        if match:
            groups.setdefault((int(row["profile_id"]), int(match.group(1))), "")

    ordered_groups: dict[int, list[int]] = {}
    for profile_id, group in groups:
        ordered_groups.setdefault(profile_id, []).append(group)
    bank_sequences = {
        (profile_id, group): index
        for profile_id, group_list in ordered_groups.items()
        for index, group in enumerate(sorted(set(group_list)), start=1)
    }
    for (profile_id, group), bank_name in groups.items():
        db.execute(
            "INSERT INTO profile_banks(profile_id,bank_sequence,group_code,bank_name,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(profile_id,group_code) DO UPDATE SET "
            "bank_name=CASE WHEN excluded.bank_name<>'' THEN excluded.bank_name ELSE profile_banks.bank_name END, "
            "updated_at=excluded.updated_at",
            (profile_id, bank_sequences[(profile_id, group)], group, bank_name, now, now),
        )
        bank = db.execute(
            "SELECT bank_id FROM profile_banks WHERE profile_id=? AND group_code=?",
            (profile_id, group),
        ).fetchone()
        db.execute(
            "UPDATE profile_values SET bank_id=? WHERE profile_id=? AND field_key LIKE ?",
            (int(bank["bank_id"]), profile_id, f"BANK_{group}%"),
        )

    # Previous releases restarted numeric suffixes inside each bank. Reassign
    # each field type's values across the whole profile in bank order so IDs
    # become unique and never overlap between banks.
    for profile in db.execute("SELECT profile_id FROM profiles").fetchall():
        profile_id = int(profile["profile_id"])
        for suffix in BANK_SUFFIXES:
            matched = []
            for row in db.execute(
                "SELECT value_id,field_key,value_sequence FROM profile_values WHERE profile_id=?",
                (profile_id,),
            ).fetchall():
                match = re.fullmatch(rf"BANK_(1[2-6][0-9]{{2}}){suffix}(?:_(\d+))?", str(row["field_key"]))
                if match:
                    matched.append((int(match.group(1)), int(match.group(2) or row["value_sequence"] or 0), int(row["value_id"])))
            matched.sort(key=lambda item: (item[0], item[1], item[2]))
            legacy_keys = [
                key for key in BANK_SUFFIX_BY_FIELD_KEY
                if BANK_SUFFIX_BY_FIELD_KEY[key] == suffix and not key.startswith("BANK_")
            ]
            legacy_max = 0
            for legacy_key in legacy_keys:
                for legacy_row in db.execute(
                    "SELECT field_key,value_sequence FROM profile_values WHERE profile_id=?",
                    (profile_id,),
                ).fetchall():
                    legacy_match = re.fullmatch(re.escape(legacy_key) + r"(?:_(\d+))?", str(legacy_row["field_key"]))
                    if legacy_match:
                        legacy_max = max(legacy_max, int(legacy_match.group(1) or legacy_row["value_sequence"] or 1))
            for _group, _old_sequence, value_id in matched:
                db.execute(
                    "UPDATE profile_values SET field_key=? WHERE value_id=?",
                    (f"__BANK_VALUE_MIGRATION_{value_id}", value_id),
                )
            for offset, (group, _old_sequence, value_id) in enumerate(matched, start=1):
                sequence = legacy_max + offset
                key = f"BANK_{group}{suffix}_{sequence:02d}"
                db.execute(
                    "UPDATE profile_values SET field_key=?,value_sequence=?,updated_at=? WHERE value_id=?",
                    (key, sequence, now, value_id),
                )

            canonical = db.execute(
                "SELECT field_number FROM field_definitions WHERE field_key=?",
                (bank_field_key(BANK_FIRST, suffix),),
            ).fetchone()
            if canonical and matched:
                current = db.execute(
                    "SELECT next_sequence FROM value_counters WHERE profile_id=? AND field_number=?",
                    (profile_id, int(canonical["field_number"])),
                ).fetchone()
                next_sequence = max(int(current["next_sequence"]) if current else 1, legacy_max + len(matched) + 1)
                db.execute(
                    "INSERT INTO value_counters(profile_id,field_number,next_sequence) VALUES(?,?,?) "
                    "ON CONFLICT(profile_id,field_number) DO UPDATE SET next_sequence=MAX(next_sequence,excluded.next_sequence)",
                    (profile_id, int(canonical["field_number"]), next_sequence),
                )
                all_group_numbers = [
                    int(row[0]) for row in db.execute(
                        "SELECT field_number FROM field_definitions WHERE field_key GLOB ?",
                        (f"BANK_1[2-6][0-9][0-9]{suffix}",),
                    ).fetchall()
                ]
                other_numbers = [number for number in all_group_numbers if number != int(canonical["field_number"])]
                if other_numbers:
                    marks = ",".join("?" for _ in other_numbers)
                    db.execute(
                        f"DELETE FROM value_counters WHERE profile_id=? AND field_number IN ({marks})",
                        (profile_id, *other_numbers),
                    )


def _migrate_value_instance_ids(db: sqlite3.Connection, now: str) -> None:
    """Persist the stable profile-scoped value ID for every stored value."""
    rows = db.execute(
        "SELECT value_id,field_key,value_sequence FROM profile_values ORDER BY profile_id,value_id"
    ).fetchall()
    for row in rows:
        key = str(row["field_key"])
        base, sequence = split_field_key(key)
        field = db.execute(
            "SELECT field_id FROM field_definitions WHERE field_key=?",
            (base,),
        ).fetchone()
        if not field or not field["field_id"]:
            continue
        public_id = str(field["field_id"])
        instance_id = public_id + _alpha_suffix(sequence) if sequence > 0 else public_id
        db.execute(
            "UPDATE profile_values SET value_instance_id=?,updated_at=? WHERE value_id=?",
            (instance_id, now, int(row["value_id"])),
        )

def _bank_counter_field_number(db: sqlite3.Connection, field_key: str, fallback: int) -> int:
    match = re.fullmatch(r"BANK_1[2-6][0-9]{2}([A-F])", field_key)
    suffix = match.group(1) if match else BANK_SUFFIX_BY_FIELD_KEY.get(field_key)
    if not suffix:
        return fallback
    canonical = bank_field_key(BANK_FIRST, suffix)
    row = db.execute(
        "SELECT field_number FROM field_definitions WHERE field_key=?",
        (canonical,),
    ).fetchone()
    return int(row["field_number"]) if row else fallback


def _ensure_bank_group_db(db: sqlite3.Connection, group: int, now: str) -> list[dict]:
    if not BANK_FIRST <= int(group) <= BANK_LAST:
        raise ValueError(f"Bank group must be between {BANK_FIRST} and {BANK_LAST}")
    created = []
    for suffix, (_base_key, label, multiple) in BANK_SUFFIXES.items():
        key = bank_field_key(group, suffix)
        public_id = bank_field_id(group, suffix)
        row = db.execute("SELECT field_number FROM field_definitions WHERE field_key=?", (key,)).fetchone()
        if row is None:
            number = int(db.execute("SELECT COALESCE(MAX(field_number),0)+1 FROM field_definitions").fetchone()[0])
            display = label
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
            "SELECT MAX(CAST(substr(field_key,6,4) AS INTEGER)) AS highest "
            "FROM field_definitions WHERE field_key GLOB 'BANK_1[2-6][0-9][0-9]A'"
        ).fetchone()
        highest = int(row["highest"] or (BANK_FIRST - 1))
        candidate = max(BANK_FIRST, highest + 1)
        return candidate if candidate <= BANK_LAST else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def split_field_key(key: str) -> tuple[str, int]:
    """Map repeatable keys such as MOBILE_02 or a custom field's _02 value."""
    bank_match = re.fullmatch(r"(BANK_1[2-6][0-9]{2}[A-F])_(\d+)", key)
    if bank_match:
        return bank_match.group(1), int(bank_match.group(2))
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


def ensure_field(field_key: str, label: str | None = None, allows_multiple: bool | None = None, category: str | None = None) -> int:
    if category is None or not str(category).strip():
        raise ValueError("A field category is required; choose one of the seven supported categories.")
    category = normalize_field_category(category)
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
        used_ids = {str(row[0]) for row in db.execute("SELECT field_id FROM field_definitions WHERE field_id GLOB '[0-9]*'")}
        try:
            public_id = allocate_field_id(category, used_ids)
        except ValueError:
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

    if category is None or not str(category).strip():
        raise ValueError("A field category is required; choose one of the seven supported categories.")
    requested_category = normalize_field_category(category)
    number = ensure_field(field_key, label, allows_multiple, requested_category)
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


def list_profile_banks(profile_id: int) -> list[dict]:
    """Return a profile's bank ownership records without exposing account values."""
    initialize()
    with _connect() as db:
        return [
            dict(row) for row in db.execute(
                "SELECT bank_id,profile_id,bank_sequence,group_code,bank_name "
                "FROM profile_banks WHERE profile_id=? ORDER BY bank_sequence,bank_id",
                (int(profile_id),),
            ).fetchall()
        ]


def update_field_label(field_key: str, label: str) -> None:
    """Update a custom field's display label without changing its identity."""
    normalized_label = str(label).strip()
    if not normalized_label:
        raise ValueError("Field label is required.")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized_label):
        raise ValueError("Field label must not contain control characters.")

    initialize()
    with _connect() as db:
        row = db.execute(
            "SELECT is_builtin, archived FROM field_definitions WHERE field_key=?",
            (str(field_key).strip().upper(),),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown field: {field_key}")
        if row["is_builtin"]:
            raise ValueError("Built-in fields cannot be modified.")
        if row["archived"]:
            raise ValueError("Archived fields cannot be modified.")
        cursor = db.execute(
            "UPDATE field_definitions SET label=? WHERE field_key=? AND is_builtin=0 AND archived=0",
            (normalized_label, str(field_key).strip().upper()),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Field label was not updated.")


def archive_field(field_key: str) -> None:
    initialize()
    normalized_key = str(field_key).strip().upper()
    with _connect() as db:
        row = db.execute(
            "SELECT is_builtin, archived FROM field_definitions WHERE field_key=?",
            (normalized_key,),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown field: {field_key}")
        if row["is_builtin"]:
            raise ValueError("Built-in fields cannot be archived.")
        if row["archived"]:
            raise ValueError(f"Field is already archived: {normalized_key}")
        db.execute(
            "UPDATE field_definitions SET archived=1 WHERE field_key=? AND is_builtin=0 AND archived=0",
            (normalized_key,),
        )


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
        # Keep bank ownership as a separate relational record. The legacy
        # BANK_####X profile keys remain only as stable export compatibility keys.
        bank_groups: dict[int, str] = {}
        for key, value in values.items():
            match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})A(?:_\d+)?", key)
            if match and str(value).strip():
                bank_groups.setdefault(int(match.group(1)), str(value).strip())
        for key in values:
            match = re.match(r"BANK_(1[2-6][0-9]{2})[A-F]", key)
            if match:
                bank_groups.setdefault(int(match.group(1)), "")
        for group, bank_name in bank_groups.items():
            existing_bank = db.execute(
                "SELECT bank_sequence FROM profile_banks WHERE profile_id=? AND group_code=?",
                (pid, group),
            ).fetchone()
            if existing_bank:
                bank_sequence = int(existing_bank["bank_sequence"])
            else:
                bank_sequence = int(db.execute(
                    "SELECT COALESCE(MAX(bank_sequence),0)+1 FROM profile_banks WHERE profile_id=?",
                    (pid,),
                ).fetchone()[0])
            db.execute(
                "INSERT INTO profile_banks(profile_id,bank_sequence,group_code,bank_name,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(profile_id,group_code) DO UPDATE SET "
                "bank_name=CASE WHEN excluded.bank_name<>'' THEN excluded.bank_name ELSE profile_banks.bank_name END, "
                "updated_at=excluded.updated_at",
                (pid, bank_sequence, group, bank_name, now, now),
            )
        bank_ids = {
            int(row["group_code"]): int(row["bank_id"])
            for row in db.execute("SELECT bank_id,group_code FROM profile_banks WHERE profile_id=?", (pid,)).fetchall()
        }

        from pdfunlocker.profiles.card_crypto import encrypt_profile_value
        for key, value in values.items():
            if key in {"PROFILE_ID", "PROFILE_NAME"}:
                continue
            base, seq = split_field_key(key)
            persisted_value = encrypt_profile_value(base, str(value))
            # Bank-group definitions are created on demand, but arbitrary new
            # custom keys must first be registered with an explicit category.
            bank_base_match = re.fullmatch(r"BANK_(1[2-6][0-9]{2})([A-F])", base)
            if bank_base_match:
                _ensure_bank_group_db(db, int(bank_base_match.group(1)), now)
            field_row = db.execute("SELECT field_number FROM field_definitions WHERE field_key=?", (base,)).fetchone()
            if not field_row and base in FIELD_ID_BY_KEY:
                number = int(db.execute("SELECT COALESCE(MAX(field_number),0)+1 AS n FROM field_definitions").fetchone()["n"])
                category = field_category_for_key(base).title()
                db.execute(
                    "INSERT INTO field_definitions(field_number,field_id,field_key,label,category,allows_multiple,is_builtin,is_custom,created_at) VALUES(?,?,?,?,?,?,1,0,?)",
                    (number, FIELD_ID_BY_KEY[base], base, base.replace("_", " ").title(), category, int(seq > 0), now),
                )
                field_row = {"field_number": number}
            if not field_row:
                raise ValueError(
                    f"Profile field '{base}' is not registered. Add it first and select one of the seven categories."
                )
            field_number = int(field_row["field_number"])
            bank_match = re.match(r"BANK_(1[2-6][0-9]{2})[A-F]", key)
            bank_id = bank_ids.get(int(bank_match.group(1))) if bank_match else None
            field_id_row = db.execute(
                "SELECT field_id,allows_multiple FROM field_definitions WHERE field_key=?",
                (base,),
            ).fetchone()
            public_id = str(field_id_row["field_id"]) if field_id_row and field_id_row["field_id"] else f"CUSTOM{field_number:04d}"
            instance_sequence = seq
            if bank_match and instance_sequence == 0:
                instance_sequence = int(bank_match.group(1)) - BANK_FIRST + 1
            value_instance_id = public_id + _alpha_suffix(instance_sequence) if instance_sequence > 0 else public_id
            db.execute(
                "INSERT INTO profile_values(profile_id,bank_id,value_instance_id,field_key,value_sequence,value,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(profile_id,field_key) DO UPDATE SET bank_id=excluded.bank_id,value_instance_id=excluded.value_instance_id,value_sequence=excluded.value_sequence,value=excluded.value,updated_at=excluded.updated_at",
                (pid, bank_id, value_instance_id, key, seq, persisted_value, now, now),
            )
            if seq > 0:
                counter_number = _bank_counter_field_number(db, base, field_number)
                db.execute(
                    "INSERT INTO value_counters(profile_id,field_number,next_sequence) VALUES(?,?,?) "
                    "ON CONFLICT(profile_id,field_number) DO UPDATE SET next_sequence=MAX(next_sequence,excluded.next_sequence)",
                    (pid, counter_number, seq + 1),
                )
        # Remove DB values absent from the current dictionary, but keep field definitions and counters.
        current = [k for k in values if k not in {"PROFILE_ID", "PROFILE_NAME"}]
        if current:
            marks = ",".join("?" for _ in current)
            db.execute(f"DELETE FROM profile_values WHERE profile_id=? AND field_key NOT IN ({marks})", (pid, *current))
        else:
            db.execute("DELETE FROM profile_values WHERE profile_id=?", (pid,))
        db.execute(
            "DELETE FROM profile_banks WHERE profile_id=? AND NOT EXISTS ("
            "SELECT 1 FROM profile_values pv WHERE pv.bank_id=profile_banks.bank_id)",
            (pid,),
        )


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
    """Return the next never-reused alphabetic value sequence.

    Bank fields share a profile-scoped sequence across all banks. Legacy
    ungrouped keys such as ACCOUNT_NUMBER_01 participate in the same sequence
    until those values are associated with a bank by the user.
    """
    initialize()
    bank_match = re.fullmatch(r"BANK_1[2-6][0-9]{2}([A-F])", field_key)
    bank_suffix = bank_match.group(1) if bank_match else BANK_SUFFIX_BY_FIELD_KEY.get(field_key)
    highest = 0

    def inspect_key(key: str, sequence_hint: int = 0) -> None:
        nonlocal highest
        if bank_suffix:
            bank_value = re.fullmatch(
                r"BANK_1[2-6][0-9]{2}" + re.escape(bank_suffix) + r"(?:_(\d+))?",
                key,
            )
            if bank_value:
                highest = max(highest, int(bank_value.group(1) or sequence_hint or 1))
                return
            for legacy_key, suffix in BANK_SUFFIX_BY_FIELD_KEY.items():
                if suffix != bank_suffix or legacy_key.startswith("BANK_"):
                    continue
                legacy_value = re.fullmatch(re.escape(legacy_key) + r"(?:_(\d+))?", key)
                if legacy_value:
                    highest = max(highest, int(legacy_value.group(1) or sequence_hint or 1))
                    return
            return
        if key == field_key:
            highest = max(highest, 1)
            return
        base, sequence = split_field_key(key)
        if base == field_key and sequence > 0:
            highest = max(highest, sequence)

    if current_values:
        for key in current_values:
            inspect_key(key)

    with _connect() as db:
        if bank_suffix:
            canonical_key = bank_field_key(BANK_FIRST, bank_suffix)
            field = db.execute(
                "SELECT field_number FROM field_definitions WHERE field_key=?",
                (canonical_key,),
            ).fetchone()
            if field is None:
                return highest + 1
            counter = db.execute(
                "SELECT next_sequence FROM value_counters WHERE profile_id=? AND field_number=?",
                (int(profile_id), int(field["field_number"])),
            ).fetchone()
            next_saved = int(counter["next_sequence"]) if counter else 1
            rows = db.execute(
                "SELECT field_key,value_sequence FROM profile_values WHERE profile_id=?",
                (int(profile_id),),
            ).fetchall()
            for row in rows:
                inspect_key(str(row["field_key"]), int(row["value_sequence"] or 0))
            return max(next_saved, highest + 1)

        field = db.execute(
            "SELECT field_number FROM field_definitions WHERE field_key=?",
            (field_key,),
        ).fetchone()
        if field is None:
            return highest + 1
        counter_number = _bank_counter_field_number(db, field_key, int(field["field_number"]))
        counter = db.execute(
            "SELECT next_sequence FROM value_counters WHERE profile_id=? AND field_number=?",
            (int(profile_id), counter_number),
        ).fetchone()
        next_saved = int(counter["next_sequence"]) if counter else 1
        rows = db.execute(
            "SELECT field_key,value_sequence FROM profile_values WHERE profile_id=?",
            (int(profile_id),),
        ).fetchall()
        for row in rows:
            inspect_key(str(row["field_key"]), int(row["value_sequence"] or 0))
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
    return f"{base}{_alpha_suffix(sequence)}" if allows_multiple and sequence > 0 else base
