import sqlite3

import pytest

from pdfunlocker.profiles import card_crypto, store


def test_failed_card_encryption_rolls_back_migration_data(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "profiles.sqlite3"
    key_path = tmp_path / "keys" / "card-number.key"

    monkeypatch.setattr(store, "DB_PATH", db_path)
    monkeypatch.setattr(card_crypto, "KEY_PATH", key_path)

    store.initialize()
    store.ensure_bank_group(1200)

    now = "2026-11-06T00:00:00+00:00"

    with sqlite3.connect(db_path) as db:
        db.execute(
            "INSERT INTO profiles(profile_id,name,created_at,updated_at) "
            "VALUES(1,'Migration Test',?,?)",
            (now, now),
        )

        db.executemany(
            "INSERT INTO profile_values"
            "(profile_id,field_key,value_sequence,value,created_at,updated_at) "
            "VALUES(1,?,?,?,?,?)",
            [
                (
                    "BANK_1200F_01",
                    1,
                    "4111111111111111",
                    now,
                    now,
                ),
                (
                    "BANK_1200F_02",
                    2,
                    "5555555555554444",
                    now,
                    now,
                ),
            ],
        )

        db.execute(
            "UPDATE schema_metadata SET value='3' "
            "WHERE key='schema_version'"
        )

    original_encrypt = card_crypto.encrypt_profile_value
    call_count = 0

    def fail_on_second_card(field_key, value):
        nonlocal call_count
        call_count += 1

        if call_count == 2:
            raise RuntimeError("Injected encryption failure for rollback test")

        return original_encrypt(field_key, value)

    monkeypatch.setattr(
        card_crypto,
        "encrypt_profile_value",
        fail_on_second_card,
    )

    with pytest.raises(RuntimeError, match="Injected encryption failure"):
        store.initialize()

    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row

        values = db.execute(
            "SELECT field_key,value,value_sequence,bank_id,value_instance_id "
            "FROM profile_values WHERE profile_id=1 ORDER BY value_id"
        ).fetchall()

        version = db.execute(
            "SELECT value FROM schema_metadata WHERE key='schema_version'"
        ).fetchone()["value"]

        bank_count = db.execute(
            "SELECT COUNT(*) FROM profile_banks WHERE profile_id=1"
        ).fetchone()[0]

    assert version == "3"
    assert bank_count == 0
    assert len(values) == 2

    assert [row["field_key"] for row in values] == [
        "BANK_1200F_01",
        "BANK_1200F_02",
    ]

    assert [row["value"] for row in values] == [
        "4111111111111111",
        "5555555555554444",
    ]

    assert all(row["bank_id"] is None for row in values)
    assert all(row["value_instance_id"] is None for row in values)
