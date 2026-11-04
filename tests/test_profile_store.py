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
            "TITLE": "0100", "FIRST_NAME": "0200", "LAST_NAME": "0300",
            "MIDDLE_NAME": "0400", "MOTHER_NAME": "0500", "DOB": "0600",
            "MOBILE": "0700", "EMAIL": "0800", "PINCODE": "0900",
            "PAN": "1000", "AADHAAR": "1100",
            "INCORPORATION_DATE": "1700", "TAN": "1800", "GSTIN": "1900",
            "EMPLOYEE_ID": "2000", "UAN": "2100", "PPO_NUMBER": "2200",
            "PRAN": "2300", "POLICY_NUMBER": "2400",
            "BANK_1200A": "1200A", "BANK_1200F": "1200F",
        }
        for key, public_id in expected.items():
            self.assertEqual(fields[key]["field_id"], public_id)
        self.assertEqual(fields["ACCOUNT_NUMBER"]["archived"], 1)

    def test_custom_field_ids_are_sequential(self):
        account_id, _ = store.add_field("Account Number", "ACCOUNT_NUMBER", True)
        card_id, _ = store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        self.assertEqual(account_id, 6)
        self.assertGreater(card_id, 30)

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
            "BANK_1200A": "Example Bank",
            "BANK_1200E_01": "1234567890",
            "BANK_1200E_02": "9876543210",
        }
        store.save_profile(path, values)
        self.assertEqual(store.load_profile(2), values)
        fields = {item["field_key"]: item for item in store.list_fields()}
        self.assertTrue(fields["BANK_1200E"]["allows_multiple"])
        self.assertEqual(fields["BANK_1200E"]["field_id"], "1200E")
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
                "BANK_1200A": "Example Bank",
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
        self.assertEqual(store.value_code(6, 1, True), "006-01")
        self.assertEqual(store.value_code(6, 2, True), "006-02")
        self.assertEqual(store.value_code(7, 3, True), "007-03")
        bank = next(item for item in store.list_fields() if item["field_id"] == "1200E")
        self.assertEqual(store.value_code(bank["field_number"], 1, True), "1200E-01")

    def test_custom_field_rejects_any_numeric_suffix(self):
        for key in ("TEST_FIELD_0", "TEST_FIELD_9", "TEST_FIELD_10", "TEST_FIELD_2026"):
            with self.subTest(key=key):
                with self.assertRaisesRegex(ValueError, "numeric suffix"):
                    store.add_field("Test Field", key, False)

    def test_existing_custom_field_rejects_category_conflict(self):
        store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        with self.assertRaisesRegex(ValueError, "existing definition was kept"):
            store.add_field("Travel Tag", "TRAVEL_TAG", True, "Financial")
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        self.assertEqual(fields["TRAVEL_TAG"]["category"], "Personal")

    def test_existing_custom_field_without_category_keeps_original_category(self):
        store.add_field("Travel Tag", "TRAVEL_TAG", True, "Personal")
        number, key = store.add_field("Travel Tag", "TRAVEL_TAG", True)
        self.assertEqual(key, "TRAVEL_TAG")
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        self.assertEqual(fields["TRAVEL_TAG"]["field_number"], number)
        self.assertEqual(fields["TRAVEL_TAG"]["category"], "Personal")

    def test_archive_does_not_delete_field(self):
        store.add_field("Test Field", "TEST_FIELD", False)
        store.archive_field("TEST_FIELD")
        all_fields = store.list_fields(include_archived=True)
        item = next(x for x in all_fields if x["field_key"] == "TEST_FIELD")
        self.assertEqual(item["archived"], 1)


if __name__ == "__main__":
    unittest.main()
