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
        fields = {item["field_key"]: item["field_number"] for item in store.list_fields()}
        self.assertEqual(fields["FIRST_NAME"], 1)
        self.assertEqual(fields["MOBILE"], 2)
        self.assertEqual(fields["LAST_NAME"], 3)
        self.assertEqual(fields["EMAIL"], 4)
        self.assertEqual(fields["PINCODE"], 5)
        self.assertEqual(fields["ACCOUNT_NUMBER"], 6)
        self.assertEqual(fields["CREDIT_CARD_NUMBER"], 7)
        self.assertEqual(fields["CUSTOMER_ID"], 8)

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

    def test_custom_repeatable_values_round_trip(self):
        store.add_field("Account Number", "ACCOUNT_NUMBER", True)
        path = Path(self.tmp.name) / "profile02.env"
        values = {"PROFILE_ID": "2", "PROFILE_NAME": "Test Two", "ACCOUNT_NUMBER_01": "123", "ACCOUNT_NUMBER_02": "456"}
        store.save_profile(path, values)
        self.assertEqual(store.load_profile(2), values)
        fields = {item["field_key"]: item for item in store.list_fields()}
        self.assertTrue(fields["ACCOUNT_NUMBER"]["allows_multiple"])
        self.assertEqual(fields["ACCOUNT_NUMBER"]["category"], "Financial")

    def test_standard_multiple_settings_and_archived_incorporation(self):
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        for key in ("MOBILE", "EMAIL", "ACCOUNT_NUMBER", "CREDIT_CARD_NUMBER", "CUSTOMER_ID", "EMPLOYEE_ID", "ROLL_NUMBER", "IFSC", "CIF", "UAN", "PRAN", "TAN", "GSTIN", "POLICY_NUMBER", "PPO_NUMBER"):
            self.assertTrue(fields[key]["allows_multiple"], key)
        for key in ("INCORPORATION_DAY", "INCORPORATION_MONTH", "INCORPORATION_YEAR"):
            self.assertEqual(fields[key]["archived"], 1)

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
        self.assertEqual(store.value_code(6, 1, True), "006A")
        self.assertEqual(store.value_code(6, 2, True), "006B")
        self.assertEqual(store.value_code(7, 3, True), "007C")

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
