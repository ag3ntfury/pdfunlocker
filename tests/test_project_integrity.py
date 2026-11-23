import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = Path.home() / "pdfunlocker"

PROFILE_TEMPLATE = "templates/profile/default_profile_template.yml"
RULE_TEMPLATE = "templates/rules/default_rule_template.yml"


class ProjectIntegrityTests(unittest.TestCase):

    def test_profile_template_exists(self):
        self.assertTrue((ROOT / PROFILE_TEMPLATE).is_file())

    def test_rule_template_exists(self):
        self.assertTrue((ROOT / RULE_TEMPLATE).is_file())

    def test_profile_template_is_valid_yaml(self):
        data = yaml.safe_load(
            (ROOT / PROFILE_TEMPLATE).read_text(encoding="utf-8")
        )
        self.assertIsInstance(data, dict)
        self.assertIn("field_registry", data)

    def test_rule_template_is_valid_yaml(self):
        data = yaml.safe_load(
            (ROOT / RULE_TEMPLATE).read_text(encoding="utf-8")
        )
        self.assertIsInstance(data, dict)
        self.assertIn("rule", data)
        self.assertIn("pattern", data)
        self.assertIn("transform", data)
        self.assertIn("status", data)

    def test_profile_template_has_14_fields(self):
        data = yaml.safe_load(
            (ROOT / PROFILE_TEMPLATE).read_text(encoding="utf-8")
        )
        fields = [
            field
            for category in data["field_registry"].values()
            for field in category
        ]
        self.assertEqual(len(fields), 14)

    def test_profile_field_ids_are_unique(self):
        data = yaml.safe_load(
            (ROOT / PROFILE_TEMPLATE).read_text(encoding="utf-8")
        )
        ids = [
            str(field["id"])
            for category in data["field_registry"].values()
            for field in category
        ]
        self.assertEqual(len(ids), len(set(ids)))

    def test_profile_field_multiplicity_is_valid(self):
        data = yaml.safe_load(
            (ROOT / PROFILE_TEMPLATE).read_text(encoding="utf-8")
        )
        for category, fields in data["field_registry"].items():
            for field in fields:
                with self.subTest(category=category, field=field["id"]):
                    self.assertIn(field["multiplicity"], {"S", "M"})

    def test_exactly_30_rule_files_exist(self):
        files = list((ROOT / "rules").glob("rule*.yml"))
        self.assertEqual(len(files), 30)

    def test_rule_filenames_are_expected(self):
        expected = {f"rule{i:05d}.yml" for i in range(1, 31)}
        actual = {path.name for path in (ROOT / "rules").glob("rule*.yml")}
        self.assertEqual(actual, expected)

    def test_all_rules_are_valid_yaml(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            with self.subTest(rule=path.name):
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIsInstance(data, dict)

    def test_rule_ids_are_unique(self):
        ids = []
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            ids.append(str(data["rule"]["id"]))
        self.assertEqual(len(ids), len(set(ids)))

    def test_rule_ids_match_filenames(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(rule=path.name):
                self.assertEqual(
                    str(data["rule"]["id"]),
                    path.stem.removeprefix("rule"),
                )

    def test_rule_ids_are_five_digits(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(rule=path.name):
                self.assertRegex(str(data["rule"]["id"]), r"^\d{5}$")

    def test_rule_required_sections(self):
        required = {"rule", "pattern", "transform", "status"}
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(rule=path.name):
                self.assertTrue(required.issubset(data))

    def test_rule_references_known_profile_fields(self):
        profile = yaml.safe_load(
            (ROOT / PROFILE_TEMPLATE).read_text(encoding="utf-8")
        )
        known = {
            str(field["id"])
            for category in profile["field_registry"].values()
            for field in category
        }

        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for field in data["pattern"]["fields"]:
                with self.subTest(rule=path.name):
                    self.assertIn(str(field["field_id"]), known)

    def test_rule_slice_modes_are_valid(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for field in data["pattern"]["fields"]:
                with self.subTest(rule=path.name):
                    self.assertIn(
                        field["slice"]["mode"],
                        {"first", "last", "full"},
                    )

    def test_rule_slice_counts_are_valid(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            for field in data["pattern"]["fields"]:
                slicing = field["slice"]
                with self.subTest(rule=path.name):
                    if slicing["mode"] in {"first", "last"}:
                        self.assertIsInstance(slicing.get("count"), int)
                        self.assertGreater(slicing["count"], 0)
                    else:
                        self.assertNotIn("count", slicing)

    def test_rule_transformations_are_valid(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(rule=path.name):
                self.assertEqual(
                    set(data["transform"]["cases"]),
                    {"lower", "upper", "raw"},
                )

    def test_rule_status_is_valid(self):
        for path in sorted((ROOT / "rules").glob("rule*.yml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            with self.subTest(rule=path.name):
                self.assertIn(data["status"], {"active", "inactive"})

    def test_profile_template_matches_production(self):
        source = ROOT / PROFILE_TEMPLATE
        target = PRODUCTION / PROFILE_TEMPLATE
        self.assertTrue(target.is_file())
        self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_rule_template_matches_production(self):
        source = ROOT / RULE_TEMPLATE
        target = PRODUCTION / RULE_TEMPLATE
        self.assertTrue(target.is_file())
        self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_all_30_rules_match_production(self):
        for source in sorted((ROOT / "rules").glob("rule*.yml")):
            target = PRODUCTION / "rules" / source.name
            with self.subTest(rule=source.name):
                self.assertTrue(target.is_file())
                self.assertEqual(source.read_bytes(), target.read_bytes())

    def test_test_settings_exist(self):
        self.assertTrue((ROOT / "config/settings.json").is_file())

    def test_test_settings_are_valid_json(self):
        data = json.loads(
            (ROOT / "config/settings.json").read_text(encoding="utf-8")
        )
        self.assertIsInstance(data, dict)

    def test_test_installation_path_is_correct(self):
        data = json.loads(
            (ROOT / "config/settings.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            Path(data["paths"]["installation"]).resolve(),
            ROOT.resolve(),
        )

    def test_test_pdf_storage_is_not_production_storage(self):
        data = json.loads(
            (ROOT / "config/settings.json").read_text(encoding="utf-8")
        )
        self.assertNotEqual(
            Path(data["paths"]["pdf_storage"]),
            Path("/storage/emulated/0/PDFUnlocker"),
        )

    def test_production_and_test_installations_are_separate(self):
        test_data = json.loads(
            (ROOT / "config/settings.json").read_text(encoding="utf-8")
        )
        production_data = json.loads(
            (PRODUCTION / "config/settings.json").read_text(encoding="utf-8")
        )
        self.assertNotEqual(
            test_data["paths"]["installation"],
            production_data["paths"]["installation"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
