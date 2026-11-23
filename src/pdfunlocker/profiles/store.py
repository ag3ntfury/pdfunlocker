"""SQLite-backed profile storage for PDF Unlocker."""

import re
import sqlite3
from contextlib import contextmanager
import string
from datetime import datetime, timezone
from pathlib import Path

import yaml


SCHEMA_VERSION = 1


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(database_path):
    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")

        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database(database_path):
    """Create only the profile-related database schema."""

    path = Path(database_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    with connect(path) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS app_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1
                    CHECK (enabled IN (0, 1)),
                execution_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS profile_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT NOT NULL,
                value_id TEXT NOT NULL,
                field_id TEXT NOT NULL,
                value TEXT NOT NULL,
                value_order INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (profile_id)
                    REFERENCES profiles(profile_id)
                    ON DELETE CASCADE,
                UNIQUE (profile_id, value_id),
                UNIQUE (profile_id, field_id, value_order)
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_profiles_execution
            ON profiles(enabled, execution_order)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_profile_values_field
            ON profile_values(profile_id, field_id)
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS profile_value_sequences (
                profile_id TEXT NOT NULL,
                field_id TEXT NOT NULL,
                next_ordinal INTEGER NOT NULL,
                PRIMARY KEY (profile_id, field_id),
                FOREIGN KEY (profile_id)
                    REFERENCES profiles(profile_id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            INSERT OR IGNORE INTO app_metadata(key, value)
            VALUES ('schema_version', ?)
        """, (str(SCHEMA_VERSION),))

        db.execute("""
            INSERT OR IGNORE INTO app_metadata(key, value)
            VALUES ('next_profile_number', '1')
        """)

    try:
        path.chmod(0o600)
    except OSError:
        pass

    return path


def load_field_registry(template_path):
    """Load and validate the approved profile field template."""

    path = Path(template_path)
    if not path.is_file():
        raise FileNotFoundError(f"Profile template not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict) or not isinstance(
        data.get("field_registry"), dict
    ):
        raise ValueError("Invalid profile template structure.")

    fields = {}

    for category, entries in data["field_registry"].items():
        if not isinstance(entries, list):
            raise ValueError(f"Invalid field category: {category}")

        for field in entries:
            field_id = str(field["id"])

            if field_id in fields:
                raise ValueError(f"Duplicate field ID: {field_id}")

            if field.get("multiplicity") not in ("S", "M"):
                raise ValueError(f"Invalid multiplicity: {field_id}")

            fields[field_id] = {
                **field,
                "id": field_id,
                "category": category,
            }

    if len(fields) != 14:
        raise ValueError(
            f"Expected 14 profile fields; template contains {len(fields)}."
        )

    return fields


def next_profile_id(database_path):
    """Return the next profile ID without reserving or consuming it."""
    with connect(database_path) as db:
        row = db.execute(
            "SELECT value FROM app_metadata WHERE key = 'next_profile_number'"
        ).fetchone()

        if row is None:
            raise RuntimeError("Profile database is not initialized.")

        number = int(row["value"])
        if number < 1:
            raise RuntimeError("Invalid next profile number in database.")

        return f"profile{number:04d}"


def create_profile(database_path, name):
    name = name.strip()

    if not name:
        raise ValueError("Profile name cannot be empty.")

    with connect(database_path) as db:
        row = db.execute(
            "SELECT value FROM app_metadata WHERE key = 'next_profile_number'"
        ).fetchone()

        if row is None:
            raise RuntimeError("Profile database is not initialized.")

        number = int(row["value"])
        profile_id = f"profile{number:04d}"

        db.execute("""
            INSERT INTO profiles (
                profile_id, name, enabled, execution_order,
                created_at, updated_at
            )
            VALUES (?, ?, 1, ?, ?, ?)
        """, (profile_id, name, number, utc_now(), utc_now()))

        db.execute("""
            UPDATE app_metadata
            SET value = ?
            WHERE key = 'next_profile_number'
        """, (str(number + 1),))

    return profile_id


def list_profiles(database_path, include_disabled=True):
    query = """
        SELECT profile_id, name, enabled, execution_order,
               created_at, updated_at
        FROM profiles
    """

    parameters = ()

    if not include_disabled:
        query += " WHERE enabled = 1"

    query += " ORDER BY execution_order, profile_id"

    with connect(database_path) as db:
        return db.execute(query, parameters).fetchall()


def get_profile(database_path, profile_id):
    with connect(database_path) as db:
        profile = db.execute(
            "SELECT * FROM profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()

        if profile is None:
            raise ValueError(f"Profile not found: {profile_id}")

        values = db.execute("""
            SELECT value_id, field_id, value, value_order
            FROM profile_values
            WHERE profile_id = ?
            ORDER BY field_id, value_order
        """, (profile_id,)).fetchall()

    return profile, values


def _ordinal_suffix(number):
    """Convert 1, 2, ... 26, 27 into A, B, ... Z, AA."""

    if number < 1:
        raise ValueError("Invalid value ordinal.")

    result = ""

    while number:
        number, remainder = divmod(number - 1, 26)
        result = string.ascii_uppercase[remainder] + result

    return result


def _normalize_and_validate(field, value):
    value = value.strip()

    if not value:
        raise ValueError("Field value cannot be empty.")

    normalization = field.get("normalization")

    if normalization == "uppercase":
        value = value.upper()

    field_type = field.get("type")

    if field_type == "date":
        if not re.fullmatch(r"\d{8}", value):
            raise ValueError("Date must use DDMMYYYY format.")

        try:
            datetime.strptime(value, "%d%m%Y")
        except ValueError:
            raise ValueError("Invalid calendar date.") from None

    validation = field.get("validation")

    if validation == "6 digits" and not re.fullmatch(r"\d{6}", value):
        raise ValueError("Pincode must contain exactly 6 digits.")

    if field_type == "email":
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address.")

    if field_type == "phone":
        if not re.fullmatch(r"[+0-9() .-]{5,25}", value):
            raise ValueError("Enter a valid phone number.")

    return value


def set_profile_value(database_path, template_path, profile_id,
                      field_id, value):
    fields = load_field_registry(template_path)
    field_id = str(field_id)

    if field_id not in fields:
        raise ValueError(f"Unknown profile field ID: {field_id}")

    field = fields[field_id]
    value = _normalize_and_validate(field, value)
    now = utc_now()

    with connect(database_path) as db:
        profile = db.execute(
            "SELECT profile_id FROM profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()

        if profile is None:
            raise ValueError(f"Profile not found: {profile_id}")

        existing = db.execute("""
            SELECT value_id
            FROM profile_values
            WHERE profile_id = ? AND field_id = ? AND value = ?
        """, (profile_id, field_id, value)).fetchone()

        if existing:
            raise ValueError(
                f"This value already exists as {existing['value_id']}."
            )

        if field["multiplicity"] == "S":
            existing = db.execute("""
                SELECT value_id, value_order
                FROM profile_values
                WHERE profile_id = ? AND field_id = ?
            """, (profile_id, field_id)).fetchone()

            if existing:
                db.execute("""
                    UPDATE profile_values
                    SET value = ?, updated_at = ?
                    WHERE profile_id = ? AND field_id = ?
                """, (value, now, profile_id, field_id))

                return existing["value_id"]

            value_id = field_id
            ordinal = 1

        else:
            sequence = db.execute("""
                SELECT next_ordinal
                FROM profile_value_sequences
                WHERE profile_id = ? AND field_id = ?
            """, (profile_id, field_id)).fetchone()

            if sequence is None:
                ordinal = 1
                db.execute("""
                    INSERT INTO profile_value_sequences
                    (profile_id, field_id, next_ordinal)
                    VALUES (?, ?, 2)
                """, (profile_id, field_id))
            else:
                ordinal = sequence["next_ordinal"]
                db.execute("""
                    UPDATE profile_value_sequences
                    SET next_ordinal = ?
                    WHERE profile_id = ? AND field_id = ?
                """, (ordinal + 1, profile_id, field_id))

            value_id = field_id + _ordinal_suffix(ordinal)

        db.execute("""
            INSERT INTO profile_values (
                profile_id, value_id, field_id, value,
                value_order, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            profile_id, value_id, field_id, value,
            ordinal, now, now,
        ))

    return value_id


def remove_profile_value(database_path, profile_id, value_id):
    with connect(database_path) as db:
        result = db.execute("""
            DELETE FROM profile_values
            WHERE profile_id = ? AND value_id = ?
        """, (profile_id, value_id))

        if result.rowcount == 0:
            raise ValueError(f"Profile value not found: {value_id}")


def set_profile_enabled(database_path, profile_id, enabled):
    with connect(database_path) as db:
        result = db.execute("""
            UPDATE profiles
            SET enabled = ?, updated_at = ?
            WHERE profile_id = ?
        """, (int(bool(enabled)), utc_now(), profile_id))

        if result.rowcount == 0:
            raise ValueError(f"Profile not found: {profile_id}")


def reorder_profile(database_path, profile_id, new_order):
    if new_order < 1:
        raise ValueError("Execution order must be 1 or greater.")

    with connect(database_path) as db:
        rows = db.execute("""
            SELECT profile_id
            FROM profiles
            ORDER BY execution_order, profile_id
        """).fetchall()

        ids = [row["profile_id"] for row in rows]

        if profile_id not in ids:
            raise ValueError(f"Profile not found: {profile_id}")

        ids.remove(profile_id)
        ids.insert(min(new_order - 1, len(ids)), profile_id)

        db.execute("UPDATE profiles SET execution_order = execution_order + 100000")

        for position, item in enumerate(ids, start=1):
            db.execute("""
                UPDATE profiles
                SET execution_order = ?, updated_at = ?
                WHERE profile_id = ?
            """, (position, utc_now(), item))


def delete_profile(database_path, profile_id):
    with connect(database_path) as db:
        result = db.execute(
            "DELETE FROM profiles WHERE profile_id = ?",
            (profile_id,),
        )

        if result.rowcount == 0:
            raise ValueError(f"Profile not found: {profile_id}")

        rows = db.execute("""
            SELECT profile_id
            FROM profiles
            ORDER BY execution_order, profile_id
        """).fetchall()

        db.execute("UPDATE profiles SET execution_order = execution_order + 100000")

        for position, row in enumerate(rows, start=1):
            db.execute("""
                UPDATE profiles
                SET execution_order = ?
                WHERE profile_id = ?
            """, (position, row["profile_id"]))
