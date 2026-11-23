import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.cli import profiles
from pdfunlocker.profiles import store


class InteractiveProfileCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "database" / "pdfunlocker.db"
        source_template = (
            Path(__file__).resolve().parents[1]
            / "templates/profile/default_profile_template.yml"
        )
        self.template = self.root / "templates" / "profile" / "default_profile_template.yml"
        self.template.parent.mkdir(parents=True)
        self.template.write_bytes(source_template.read_bytes())

    def run_create(self, answers):
        with patch("pdfunlocker.cli.profiles.prompt", side_effect=answers):
            return profiles.create_profile_interactive(root=self.root)

    def test_cancelled_name_does_not_consume_previewed_id(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = self.run_create([""])
        self.assertIsNone(result)
        self.assertIn("profile0001", output.getvalue())
        self.assertEqual(store.next_profile_id(self.database), "profile0001")
        self.assertEqual(store.list_profiles(self.database), [])

    def test_all_fields_can_be_skipped_and_profile_is_saved(self):
        fields = store.load_field_registry(self.template)
        answers = ["Empty Profile"]
        for field in fields.values():
            answers.append("")  # optional single or first multiple value
        result = self.run_create(answers)
        self.assertEqual(result, "profile0001")
        profile, values = store.get_profile(self.database, result)
        self.assertEqual(profile["name"], "Empty Profile")
        self.assertEqual(values, [])

    def test_sequential_values_and_repeatable_values_are_profile_scoped(self):
        fields = store.load_field_registry(self.template)
        answers = ["Alice Example"]
        for field_id, field in fields.items():
            if field_id == "1002":
                answers.append("Alice")
            elif field_id == "1008":
                answers.extend(["9876543210", "9876543211", ""])
            else:
                answers.append("")
        profile_id = self.run_create(answers)
        self.assertEqual(profile_id, "profile0001")

        second = store.create_profile(self.database, "Second")
        store.set_profile_value(
            self.database, self.template, second, "1008", "9876543212"
        )

        _, first_values = store.get_profile(self.database, profile_id)
        _, second_values = store.get_profile(self.database, second)

        first_mobile = [v["value"] for v in first_values if v["field_id"] == "1008"]
        second_mobile = [v["value"] for v in second_values if v["field_id"] == "1008"]
        self.assertEqual(first_mobile, ["9876543210", "9876543211"])
        self.assertEqual(second_mobile, ["9876543212"])

    def test_profile_id_becomes_permanent_after_name_is_accepted(self):
        fields = store.load_field_registry(self.template)
        answers = ["Permanent"]
        answers.extend([""] * len(fields))
        self.run_create(answers)
        store.delete_profile(self.database, "profile0001")
        self.assertEqual(store.next_profile_id(self.database), "profile0002")


if __name__ == "__main__":
    unittest.main(verbosity=2)
