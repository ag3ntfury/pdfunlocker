import json
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
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

    def test_deployment_copy_does_not_invent_machine_settings(self):
        import tempfile
        from pdfunlocker.cli.main import copy_application

        with tempfile.TemporaryDirectory() as temporary:
            production = Path(temporary) / "production"
            copy_application(ROOT, production)
            self.assertFalse((production / "config/settings.json").exists())

    def test_deployment_copy_has_templates_and_rules_and_keeps_settings(self):
        import tempfile
        from pdfunlocker.cli.main import copy_application

        with tempfile.TemporaryDirectory() as temporary:
            production = Path(temporary) / "production"
            (production / "config").mkdir(parents=True)
            sentinel = {"preserve": "existing-production-settings"}
            (production / "config/settings.json").write_text(
                json.dumps(sentinel), encoding="utf-8"
            )

            copy_application(ROOT, production)

            self.assertEqual(
                json.loads((production / "config/settings.json").read_text()),
                sentinel,
            )
            self.assertEqual(
                (production / PROFILE_TEMPLATE).read_bytes(),
                (ROOT / PROFILE_TEMPLATE).read_bytes(),
            )
            self.assertEqual(
                (production / RULE_TEMPLATE).read_bytes(),
                (ROOT / RULE_TEMPLATE).read_bytes(),
            )
            source_rules = sorted((ROOT / "rules").glob("rule*.yml"))
            deployed_rules = sorted((production / "rules").glob("rule*.yml"))
            self.assertEqual(len(deployed_rules), 30)
            self.assertEqual(
                [p.read_bytes() for p in source_rules],
                [p.read_bytes() for p in deployed_rules],
            )
            self.assertTrue((production / "database").is_dir())
            self.assertTrue((production / "profiles").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
