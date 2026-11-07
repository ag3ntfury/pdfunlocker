from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pdfunlocker.profiles import store


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = store.DB_PATH
        store.DB_PATH = Path(self.tmp.name) / "profiles.sqlite3"
        store.initialize()

    def tearDown(self):
        store.DB_PATH = self.old_path
        self.tmp.cleanup()

    def test_reserved_builtin_ids(self):
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        expected = {
            "TITLE": "1173", "FIRST_NAME": "1248", "LAST_NAME": "1371",
            "MIDDLE_NAME": "1302", "MOTHER_NAME": "1429", "DOB": "1506",
            "MOBILE": "1578", "EMAIL": "1641", "PINCODE": "1705",
            "PAN": "3197", "AADHAAR": "3268",
            "INCORPORATION_DATE": "6137", "TAN": "6194", "GSTIN": "6267",
            "EMPLOYEE_ID": "7141", "UAN": "7204", "PPO_NUMBER": "7276",
            "PRAN": "7331", "POLICY_NUMBER": "8173",
            "BANK_1200A": "4169", "BANK_1200F": "4487",
        }
        for key, public_id in expected.items():
            self.assertEqual(fields[key]["field_id"], public_id)
        self.assertEqual(fields["ACCOUNT_NUMBER"]["archived"], 1)

    def test_custom_field_requires_category_and_gets_permanent_numeric_id(self):
        with self.assertRaisesRegex(ValueError, "category is required"):
            store.add_field("Travel Tag", "TRAVEL_TAG", True)
        number, key = store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        item = next(row for row in store.list_fields(include_archived=True) if row["field_key"] == key)
        self.assertGreater(number, 0)
        self.assertTrue(1001 <= int(item["field_id"]) <= 3000)


    def test_custom_field_label_update_uses_store_validation(self):
        _, key = store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        before = next(row for row in store.list_fields(include_archived=True) if row["field_key"] == key)
        store.update_field_label(key, "Trip Reference")
        item = next(row for row in store.list_fields(include_archived=True) if row["field_key"] == key)
        self.assertEqual(item["label"], "Trip Reference")
        self.assertEqual(item["field_id"], before["field_id"])
        with self.assertRaisesRegex(ValueError, "required"):
            store.update_field_label(key, "   ")
        with self.assertRaisesRegex(ValueError, "control characters"):
            store.update_field_label(key, "Bad\nLabel")

    def test_field_archive_rejects_unknown_and_already_archived_fields(self):
        store.add_field("Travel Tag", "TRAVEL_TAG", False, "Personal")
        store.archive_field("TRAVEL_TAG")
        item = next(row for row in store.list_fields(include_archived=True) if row["field_key"] == "TRAVEL_TAG")
        self.assertEqual(item["archived"], 1)
        with self.assertRaisesRegex(ValueError, "already archived"):
            store.archive_field("TRAVEL_TAG")
        with self.assertRaisesRegex(ValueError, "Unknown field"):
            store.archive_field("NOT_REGISTERED")

    def test_save_profile_rejects_unregistered_custom_key_without_category(self):
        path = Path(self.tmp.name) / "unregistered.env"
        values = {
            "PROFILE_ID": "55",
            "PROFILE_NAME": "Unregistered",
            "TRAVEL_NOTE_01": "A note",
        }
        with self.assertRaisesRegex(ValueError, "select one of the seven categories"):
            store.save_profile(path, values)
        self.assertIsNone(store.load_profile(55))

    def test_profile_round_trip_keeps_legacy_keys(self):
        path = Path(self.tmp.name) / "profile01.env"
        values = {"PROFILE_ID": "1", "PROFILE_NAME": "Test", "FIRST_NAME": "Asha", "MOBILE_01": "+919876543210", "ACCOUNT_NUMBER_01": "123456"}
        store.save_profile(path, values)
        loaded = store.load_profile(1)
        self.assertEqual(loaded, values)

    def test_bank_repeatable_values_round_trip(self):
        store.ensure_bank_group(1200)
        path = Path(self.tmp.name) / "profile02.env"
        values = {
            "PROFILE_ID": "2", "PROFILE_NAME": "Test Two",
            "BANK_1200A_01": "Example Bank",
            "BANK_1200E_01": "1234567890",
            "BANK_1200E_02": "9876543210",
        }
        store.save_profile(path, values)
        self.assertEqual(store.load_profile(2), values)
        fields = {item["field_key"]: item for item in store.list_fields()}
        self.assertTrue(fields["BANK_1200E"]["allows_multiple"])
        self.assertEqual(fields["BANK_1200E"]["field_id"], "4424")
        self.assertEqual(fields["BANK_1200E"]["category"], "Banking")

    def test_standard_multiple_settings_and_archived_incorporation(self):
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        for key in ("MOBILE", "EMAIL", "ACCOUNT_NUMBER", "CREDIT_CARD_NUMBER", "CUSTOMER_ID", "EMPLOYEE_ID", "ROLL_NUMBER", "IFSC", "CIF", "UAN", "PRAN", "TAN", "GSTIN", "POLICY_NUMBER", "PPO_NUMBER"):
            self.assertTrue(fields[key]["allows_multiple"], key)
        for key in ("INCORPORATION_DAY", "INCORPORATION_MONTH", "INCORPORATION_YEAR"):
            self.assertEqual(fields[key]["archived"], 1)


    def test_bank_card_is_encrypted_in_database_and_decrypted_only_by_rule_crypto(self):
        from pdfunlocker.profiles import card_crypto
        old_key_path = card_crypto.KEY_PATH
        card_crypto.KEY_PATH = Path(self.tmp.name) / "keys" / "card-number.key"
        try:
            store.ensure_bank_group(1200)
            path = Path(self.tmp.name) / "profile-card.env"
            values = {
                "PROFILE_ID": "9", "PROFILE_NAME": "Card Test",
                "BANK_1200A_01": "Example Bank",
                "BANK_1200F_01": "4111111111111111",
            }
            store.save_profile(path, values)
            with store._connect() as db:
                raw = db.execute(
                    "SELECT value FROM profile_values WHERE profile_id=9 AND field_key='BANK_1200F_01'"
                ).fetchone()[0]
            self.assertTrue(card_crypto.is_encrypted_card(raw))
            self.assertNotIn("4111111111111111", raw)
            self.assertEqual(card_crypto.decrypt_card_number(raw), "4111111111111111")
            self.assertEqual(store.load_profile(9)["BANK_1200F_01"], raw)
        finally:
            card_crypto.KEY_PATH = old_key_path


    def test_initialize_encrypts_preexisting_plaintext_card_values(self):
        from pdfunlocker.profiles import card_crypto
        old_key_path = card_crypto.KEY_PATH
        card_crypto.KEY_PATH = Path(self.tmp.name) / "keys" / "card-number.key"
        try:
            store.ensure_bank_group(1200)
            with store._connect() as db:
                now = "2026-11-03T00:00:00+00:00"
                db.execute(
                    "INSERT INTO profiles(profile_id,name,created_at,updated_at) VALUES(77,'Legacy Card',?,?)",
                    (now, now),
                )
                db.execute(
                    "INSERT INTO profile_values(profile_id,field_key,value_sequence,value,created_at,updated_at) VALUES(77,'BANK_1200F_01',1,'4111111111111111',?,?)",
                    (now, now),
                )
            store.initialize()
            with store._connect() as db:
                encrypted = db.execute(
                    "SELECT value FROM profile_values WHERE profile_id=77 AND field_key='BANK_1200F_01'"
                ).fetchone()[0]
            assert card_crypto.is_encrypted_card(encrypted)
            assert card_crypto.decrypt_card_number(encrypted) == "4111111111111111"
        finally:
            card_crypto.KEY_PATH = old_key_path

    def test_value_sequence_is_not_reused_after_deletion(self):
        path = Path(self.tmp.name) / "profile03.env"
        original = {
            "PROFILE_ID": "3",
            "PROFILE_NAME": "Counter Test",
            "ACCOUNT_NUMBER_03": "test-value",
        }
        store.save_profile(path, original)
        self.assertEqual(store.next_value_sequence(3, "ACCOUNT_NUMBER", {}), 4)

        without_value = {
            "PROFILE_ID": "3",
            "PROFILE_NAME": "Counter Test",
        }
        store.save_profile(path, without_value)
        self.assertEqual(store.next_value_sequence(3, "ACCOUNT_NUMBER", {}), 4)

    def test_value_code_uses_alpha_suffix(self):
        self.assertEqual(store.value_code(6, 1, True), "4424A")
        self.assertEqual(store.value_code(6, 2, True), "4424B")
        self.assertEqual(store.value_code(7, 3, True), "4487C")
        bank = next(item for item in store.list_fields() if item["field_key"] == "BANK_1200E")
        self.assertEqual(store.value_code(bank["field_number"], 1, True), "4424A")


    def test_bank_value_ids_are_profile_scoped_and_shared_across_banks(self):
        store.ensure_bank_group(1200)
        store.ensure_bank_group(1201)
        p1 = {
            "PROFILE_ID": "21", "PROFILE_NAME": "Profile One",
            "BANK_1200A_01": "SBI", "BANK_1200E_01": "111122223333",
            "BANK_1200E_02": "222233334444",
            "BANK_1201A_02": "HDFC", "BANK_1201E_03": "333344445555",
        }
        store.save_profile(Path(self.tmp.name) / "p21.env", p1)
        self.assertEqual(store.next_value_sequence(21, "BANK_1201E", p1), 4)
        self.assertEqual(store.value_code(6, 1, True), "4424A")

        p2 = {
            "PROFILE_ID": "22", "PROFILE_NAME": "Profile Two",
            "BANK_1200A_01": "ICICI", "BANK_1200E_01": "444455556666",
        }
        store.save_profile(Path(self.tmp.name) / "p22.env", p2)
        self.assertEqual(store.next_value_sequence(22, "BANK_1200E", p2), 2)

        with store._connect() as db:
            bank_rows = db.execute(
                "SELECT profile_id, bank_name, bank_id FROM profile_banks ORDER BY profile_id, bank_sequence"
            ).fetchall()
            owned_values = db.execute(
                "SELECT profile_id, field_key, bank_id FROM profile_values WHERE field_key LIKE 'BANK_%' ORDER BY profile_id, field_key"
            ).fetchall()
        self.assertEqual([(row[0], row[1]) for row in bank_rows], [(21, "SBI"), (21, "HDFC"), (22, "ICICI")])
        self.assertTrue(all(row[2] is not None for row in owned_values))

    def test_custom_field_rejects_any_numeric_suffix(self):
        for key in ("TEST_FIELD_0", "TEST_FIELD_9", "TEST_FIELD_10", "TEST_FIELD_2026"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "numeric suffix"):
                    store.add_field("Test Field", key, False, "Personal")

    def test_existing_custom_field_rejects_category_conflict(self):
        store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        with self.assertRaisesRegex(ValueError, "existing definition was kept"):
            store.add_field("Travel Tag", "TRAVEL_TAG", True, "Banking")
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        self.assertEqual(fields["TRAVEL_TAG"]["category"], "Personal")

    def test_existing_custom_field_still_requires_explicit_category(self):
        store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        with self.assertRaisesRegex(ValueError, "category is required"):
            store.add_field("Travel Tag", "TRAVEL_TAG", True)
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        self.assertEqual(fields["TRAVEL_TAG"]["category"], "Personal")

    def test_archive_does_not_delete_field(self):
        store.add_field("Test Field", "TEST_FIELD", False, "Personal")
        store.archive_field("TEST_FIELD")
        all_fields = store.list_fields(include_archived=True)
        item = next(x for x in all_fields if x["field_key"] == "TEST_FIELD")
        self.assertEqual(item["archived"], 1)


    def test_v3_bank_group_data_migrates_to_shared_type_ids_and_explicit_bank_ownership(self):
        import sqlite3
        from unittest.mock import patch
        from pdfunlocker.profiles import card_crypto

        db_path = store.DB_PATH
        with sqlite3.connect(db_path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            # Simulate the previous v3 schema: bank group IDs were separate and
            # profile_values had no bank_id column.
            db.execute("DELETE FROM profile_values")
            db.execute("DELETE FROM value_counters")
            db.execute("DELETE FROM profile_banks")
            db.execute("DELETE FROM profiles")
            db.execute("DROP INDEX IF EXISTS idx_profile_values_instance_id")
            db.execute("ALTER TABLE profile_values DROP COLUMN value_instance_id")
            db.execute("ALTER TABLE profile_values DROP COLUMN bank_id")
            db.execute("UPDATE schema_metadata SET value='3' WHERE key='schema_version'")
            for group in (1200, 1201):
                for index, suffix in enumerate("ABCDEF", start=1):
                    key = f"BANK_{group}{suffix}"
                    number = 100 + (group - 1200) * 10 + index
                    db.execute(
                        "INSERT OR REPLACE INTO field_definitions"
                        "(field_number,field_id,field_key,label,category,allows_multiple,archived,is_builtin,is_custom,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (number, f"{group}{suffix}", key, suffix, "Banking", int(suffix in "EF"), 0, 1, 0, "2026-11-05T00:00:00+00:00"),
                    )
            now = "2026-11-05T00:00:00+00:00"
            for key, public_id, label in (
                ("ACCOUNT_NUMBER", "006", "Account Number"),
                ("CREDIT_CARD_NUMBER", "007", "Credit Card Number"),
            ):
                db.execute(
                    "UPDATE field_definitions SET field_id=?,label=?,category='Banking',allows_multiple=1,archived=1 WHERE field_key=?",
                    (public_id, label, key),
                )
            db.execute("CREATE UNIQUE INDEX idx_field_definitions_field_id ON field_definitions(field_id)")
            db.execute(
                "INSERT INTO profiles(profile_id,name,created_at,updated_at) VALUES(1,'Legacy',?,?)",
                (now, now),
            )
            legacy_values = [
                ("BANK_1200A", 0, "SBI"),
                ("BANK_1200E_01", 1, "111122223333"),
                ("BANK_1200E_02", 2, "222233334444"),
                ("BANK_1201A", 0, "HDFC"),
                ("BANK_1201E_03", 3, "333344445555"),
                ("ACCOUNT_NUMBER_01", 1, "LEGACY-ACCOUNT"),
                ("CREDIT_CARD_NUMBER_01", 1, "4111111111111111"),
            ]
            for key, sequence, value in legacy_values:
                db.execute(
                    "INSERT INTO profile_values(profile_id,field_key,value_sequence,value,created_at,updated_at) "
                    "VALUES(1,?,?,?,?,?)",
                    (key, sequence, value, now, now),
                )
            db.execute(
                "INSERT INTO value_counters(profile_id,field_number,next_sequence) VALUES(1,105,3)"
            )
            db.execute(
                "INSERT INTO value_counters(profile_id,field_number,next_sequence) VALUES(1,115,4)"
            )

        with patch.object(
            card_crypto,
            "KEY_PATH",
            Path(self.tmp.name) / "keys" / "migration-card-number.key",
        ):
            store.initialize()
            values = store.load_profile(1)
            migrated_card = values["CREDIT_CARD_NUMBER_01"]
            self.assertTrue(card_crypto.is_encrypted_card(migrated_card))
            self.assertEqual(
                card_crypto.decrypt_card_number(migrated_card),
                "4111111111111111",
            )
        assert values["BANK_1200A_01"] == "SBI"
        assert values["BANK_1201A_02"] == "HDFC"
        assert values["BANK_1200E_02"] == "111122223333"
        assert values["BANK_1200E_03"] == "222233334444"
        assert values["BANK_1201E_04"] == "333344445555"
        assert store.next_value_sequence(1, "BANK_1201E", {}) == 5
        with store._connect() as db:
            banks = db.execute(
                "SELECT bank_sequence,group_code,bank_name FROM profile_banks WHERE profile_id=1 ORDER BY bank_sequence"
            ).fetchall()
            owned = db.execute(
                "SELECT COUNT(*) FROM profile_values WHERE profile_id=1 AND field_key LIKE 'BANK_%' AND bank_id IS NOT NULL"
            ).fetchone()[0]
            instance_ids = db.execute(
                "SELECT value_instance_id FROM profile_values WHERE profile_id=1 AND field_key LIKE 'BANK_%E_%' ORDER BY value_sequence"
            ).fetchall()
            all_ids = {
                row[0]: row[1]
                for row in db.execute(
                    "SELECT field_key,value_instance_id FROM profile_values WHERE profile_id=1"
                ).fetchall()
            }
        assert [(row[0], row[1], row[2]) for row in banks] == [(1, 1200, "SBI"), (2, 1201, "HDFC")]
        assert owned == len(legacy_values) - 2
        assert [row[0] for row in instance_ids] == ["4424B", "4424C", "4424D"]
        assert all_ids["ACCOUNT_NUMBER_01"] == "4424A"
        assert all_ids["CREDIT_CARD_NUMBER_01"] == "4487A"
        assert len(set(all_ids.values())) == len(all_ids)

    def test_alpha_suffix_is_unbounded(self):
        self.assertEqual(store._alpha_suffix(1), "A")
        self.assertEqual(store._alpha_suffix(26), "Z")
        self.assertEqual(store._alpha_suffix(27), "AA")
        self.assertEqual(store._alpha_suffix(28), "AB")
        self.assertEqual(store.value_code(6, 27, True), "4424AA")


if __name__ == "__main__":
    unittest.main()
