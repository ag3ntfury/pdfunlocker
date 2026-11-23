import tempfile
import unittest
from pathlib import Path

from pdfunlocker.profiles import store


TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "templates/profile/default_profile_template.yml"
)


class ProfileStoreRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = Path(self.temp.name) / "database" / "test.db"
        store.initialize_database(self.db_path)
        self.profile = store.create_profile(self.db_path, "Test Profile")

    def set_value(self, field_id, value):
        return store.set_profile_value(
            self.db_path, TEMPLATE, self.profile, field_id, value
        )

    def test_database_created(self):
        self.assertTrue(self.db_path.is_file())

    def test_database_integrity(self):
        with store.connect(self.db_path) as db:
            result = db.execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(result, "ok")

    def test_foreign_keys_enabled(self):
        with store.connect(self.db_path) as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_database_permissions(self):
        self.assertEqual(self.db_path.stat().st_mode & 0o777, 0o600)

    def test_initialize_twice_preserves_profile(self):
        store.initialize_database(self.db_path)
        self.assertEqual(len(store.list_profiles(self.db_path)), 1)

    def test_template_has_fourteen_fields(self):
        self.assertEqual(len(store.load_field_registry(TEMPLATE)), 14)

    def test_profile_ids_increment(self):
        second = store.create_profile(self.db_path, "Second")
        self.assertEqual(self.profile, "profile0001")
        self.assertEqual(second, "profile0002")

    def test_profile_ids_not_reused_after_delete(self):
        store.delete_profile(self.db_path, self.profile)
        second = store.create_profile(self.db_path, "Second")
        self.assertEqual(second, "profile0002")

    def test_profile_name_is_trimmed(self):
        profile = store.create_profile(self.db_path, "  Another Profile  ")
        self.assertEqual(store.get_profile(self.db_path, profile)[0]["name"],
                         "Another Profile")

    def test_blank_profile_name_rejected(self):
        with self.assertRaises(ValueError):
            store.create_profile(self.db_path, "   ")

    def test_single_value_field(self):
        value_id = self.set_value("1002", "Rupesh")
        self.assertEqual(value_id, "1002")

    def test_single_value_can_be_updated(self):
        self.set_value("1002", "First")
        self.set_value("1002", "Second")
        _, values = store.get_profile(self.db_path, self.profile)
        found = [v for v in values if v["field_id"] == "1002"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["value"], "Second")

    def test_pan_is_uppercase(self):
        self.set_value("1006", "abcde1234f")
        _, values = store.get_profile(self.db_path, self.profile)
        self.assertEqual(values[0]["value"], "ABCDE1234F")

    def test_vehicle_registration_is_uppercase(self):
        self.set_value("1035", "gj01ab1234")
        _, values = store.get_profile(self.db_path, self.profile)
        self.assertEqual(values[0]["value"], "GJ01AB1234")

    def test_chassis_number_is_uppercase(self):
        self.set_value("1036", "abc123xyz")
        _, values = store.get_profile(self.db_path, self.profile)
        self.assertEqual(values[0]["value"], "ABC123XYZ")

    def test_valid_birth_date(self):
        self.set_value("1005", "14021990")

    def test_invalid_birth_date_format(self):
        with self.assertRaises(ValueError):
            self.set_value("1005", "19900214")

    def test_invalid_calendar_date(self):
        with self.assertRaises(ValueError):
            self.set_value("1005", "31022000")

    def test_valid_pincode(self):
        self.set_value("1007", "361305")

    def test_invalid_pincode(self):
        for value in ("12345", "12A456", "1234567"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.set_value("1007", value)

    def test_valid_email(self):
        self.set_value("1009", "test@example.com")

    def test_invalid_email(self):
        with self.assertRaises(ValueError):
            self.set_value("1009", "not-an-email")

    def test_valid_phone(self):
        self.set_value("1008", "+91 98765 43210")

    def test_invalid_phone(self):
        with self.assertRaises(ValueError):
            self.set_value("1008", "phone-number")

    def test_empty_value_rejected(self):
        with self.assertRaises(ValueError):
            self.set_value("1002", "   ")

    def test_unknown_field_rejected(self):
        with self.assertRaises(ValueError):
            self.set_value("9999", "value")

    def test_multiple_values_get_suffixes(self):
        self.assertEqual(self.set_value("1008", "9876543210"), "1008A")
        self.assertEqual(self.set_value("1008", "9876543211"), "1008B")
        self.assertEqual(self.set_value("1008", "9876543212"), "1008C")

    def test_duplicate_multiple_value_rejected(self):
        self.set_value("1008", "9876543210")
        with self.assertRaises(ValueError):
            self.set_value("1008", "9876543210")

    def test_deleted_suffix_is_not_reused(self):
        first = self.set_value("1008", "9876543210")
        self.set_value("1008", "9876543211")
        store.remove_profile_value(self.db_path, self.profile, first)
        third = self.set_value("1008", "9876543212")
        self.assertEqual(third, "1008C")

    def test_enable_disable_profile(self):
        store.set_profile_enabled(self.db_path, self.profile, False)
        self.assertEqual(
            store.get_profile(self.db_path, self.profile)[0]["enabled"], 0
        )
        store.set_profile_enabled(self.db_path, self.profile, True)
        self.assertEqual(
            store.get_profile(self.db_path, self.profile)[0]["enabled"], 1
        )

    def test_disabled_profiles_can_be_filtered(self):
        store.set_profile_enabled(self.db_path, self.profile, False)
        self.assertEqual(
            store.list_profiles(self.db_path, include_disabled=False), []
        )

    def test_profile_reordering(self):
        second = store.create_profile(self.db_path, "Second")
        third = store.create_profile(self.db_path, "Third")
        store.reorder_profile(self.db_path, third, 1)
        ids = [p["profile_id"] for p in store.list_profiles(self.db_path)]
        self.assertEqual(ids, [third, self.profile, second])

    def test_invalid_reorder_position(self):
        with self.assertRaises(ValueError):
            store.reorder_profile(self.db_path, self.profile, 0)

    def test_delete_cascades_profile_values(self):
        self.set_value("1002", "Rupesh")
        store.delete_profile(self.db_path, self.profile)
        with store.connect(self.db_path) as db:
            count = db.execute("SELECT COUNT(*) FROM profile_values").fetchone()[0]
        self.assertEqual(count, 0)

    def test_ordinal_suffix_boundaries(self):
        expected = {1: "A", 26: "Z", 27: "AA", 28: "AB", 52: "AZ", 53: "BA"}
        for number, suffix in expected.items():
            with self.subTest(number=number):
                self.assertEqual(store._ordinal_suffix(number), suffix)


if __name__ == "__main__":
    unittest.main(verbosity=2)
