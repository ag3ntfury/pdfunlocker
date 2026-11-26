import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.unlocker import engine
from pdfunlocker.unlocker import qpdf


class UnlockEngineTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

        self.source = self.root / "input.pdf"
        self.source.write_bytes(b"synthetic encrypted PDF")

        self.output = self.root / "output"
        self.database = self.root / "learning.db"

        self.rules = self.root / "rules"
        self.rules.mkdir()

        self.rule_id = "00001"
        self.profile_id = "test-profile"

        self.rule_file = self.rules / "rule00001.yml"
        self.rule_file.write_text(
            "rule:\n  id: '00001'\nstatus: active\n",
            encoding="utf-8",
        )

        self.template = self.root / "template.yml"
        self.template.write_text("fields: {}\n", encoding="utf-8")

        self.candidates = {
            "candidate_set_fingerprint": "candidate-set-test",
            "candidates": [
                {
                    "number": 1,
                    "value": "synthetic-password-one",
                    "fingerprint": "fingerprint-one",
                },
                {
                    "number": 2,
                    "value": "synthetic-password-two",
                    "fingerprint": "fingerprint-two",
                },
            ],
        }

        self.run_details = {
            "run": {
                "run_id": 1,
                "sha256": "test-sha256",
                "outcome": "running",
                "attempted_count": 0,
            },
            "attempts": [],
        }

        self.common_patches = [
            patch.object(
                engine.qpdf,
                "calculate_sha256",
                return_value="test-sha256",
            ),
            patch.object(
                engine.qpdf,
                "detect_encryption",
                return_value=qpdf.QPDFResult("encrypted"),
            ),
            patch.object(
                engine,
                "load_active_rules",
                return_value=[self.rule_id],
            ),
            patch.object(
                engine,
                "generate_candidates",
                return_value=self.candidates,
            ),
            patch.object(
                engine,
                "start_rule_run",
                return_value={
                    "status": "started",
                    "run_id": 1,
                    "attempted_candidates": [],
                },
            ),
            patch.object(
                engine,
                "get_rule_run",
                return_value=self.run_details,
            ),
            patch.object(
                engine,
                "record_candidate_attempt",
            ),
            patch.object(
                engine,
                "fail_rule_run",
            ),
            patch.object(
                engine,
                "finish_rule_run",
            ),
        ]

        self.entered_patches = []

        for item in self.common_patches:
            self.entered_patches.append(item)
            item.start()

    def tearDown(self):
        for item in reversed(self.entered_patches):
            item.stop()

        self.temp.cleanup()

    def call_engine(self, **kwargs):
        options = {
            "input_path": self.source,
            "output_directory": self.output,
            "database_path": self.database,
            "profile_id": self.profile_id,
            "rule_id": self.rule_id,
            "template_path": self.template,
            "rules_directory": self.rules,
            "attempts_per_second": 50,
        }
        options.update(kwargs)
        return engine.unlock_one_rule(**options)

    def test_missing_input_is_rejected(self):
        result = self.call_engine(
            input_path=self.root / "missing.pdf"
        )

        self.assertEqual(result["status"], "corrupted")
        self.assertEqual(result["error_code"], "input_missing")

    def test_reserved_test_rule_is_blocked_by_default(self):
        result = self.call_engine(rule_id="00000")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "test_rule_disabled")

    def test_invalid_attempt_rate_is_rejected(self):
        result = self.call_engine(attempts_per_second=51)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "invalid_attempt_rate")

    def test_unencrypted_pdf_is_not_processed(self):
        with patch.object(
            engine.qpdf,
            "detect_encryption",
            return_value=qpdf.QPDFResult("not_encrypted"),
        ):
            result = self.call_engine()

        self.assertEqual(result["status"], "not_encrypted")
        engine.generate_candidates.assert_not_called()

    def test_uncertain_encryption_requires_review(self):
        with patch.object(
            engine.qpdf,
            "detect_encryption",
            return_value=qpdf.QPDFResult(
                "uncertain",
                error_code="encryption_detection_failed",
            ),
        ):
            result = self.call_engine()

        self.assertEqual(result["status"], "review")
        self.assertEqual(
            result["error_code"],
            "encryption_detection_failed",
        )

    def test_successful_candidate_returns_verified_output(self):
        destination = (
            self.output
            / "test-sha256_run1_candidate1.pdf"
        )

        def decrypt(source, output, password, timeout=120):
            self.assertEqual(password, "synthetic-password-one")
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"decrypted synthetic PDF")

            return qpdf.QPDFResult(
                "unlocked",
                output_path=str(output),
                output_sha256="output-sha256",
            )

        with patch.object(
            engine.qpdf,
            "decrypt_pdf",
            side_effect=decrypt,
        ) as decrypt_mock:
            result = self.call_engine()

        self.assertEqual(result["status"], "unlocked")
        self.assertEqual(result["attempted_count"], 1)
        self.assertEqual(result["output_path"], str(destination))
        self.assertTrue(destination.is_file())

        decrypt_mock.assert_called_once()

        engine.record_candidate_attempt.assert_called_once_with(
            self.database,
            1,
            1,
            "fingerprint-one",
            "success",
        )

        self.assertNotIn(
            "synthetic-password-one",
            str(result),
        )
        self.assertNotIn(
            "synthetic-password-two",
            str(result),
        )

    def test_wrong_password_continues_to_next_candidate(self):
        calls = []

        def decrypt(source, output, password, timeout=120):
            calls.append(password)

            if password == "synthetic-password-one":
                return qpdf.QPDFResult("wrong_password")

            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_bytes(b"decrypted synthetic PDF")

            return qpdf.QPDFResult(
                "unlocked",
                output_path=str(output),
                output_sha256="output-sha256",
            )

        with patch.object(
            engine.qpdf,
            "decrypt_pdf",
            side_effect=decrypt,
        ):
            result = self.call_engine()

        self.assertEqual(result["status"], "unlocked")
        self.assertEqual(result["attempted_count"], 2)

        self.assertEqual(
            calls,
            [
                "synthetic-password-one",
                "synthetic-password-two",
            ],
        )

        self.assertEqual(
            engine.record_candidate_attempt.call_count,
            2,
        )

    def test_all_wrong_candidates_mark_run_exhausted(self):
        with patch.object(
            engine.qpdf,
            "decrypt_pdf",
            return_value=qpdf.QPDFResult("wrong_password"),
        ):
            result = self.call_engine()

        self.assertEqual(result["status"], "locked")
        self.assertEqual(result["attempted_count"], 2)

        engine.finish_rule_run.assert_called_once_with(
            self.database,
            1,
            "exhausted",
        )

    def test_existing_invalid_output_is_not_overwritten(self):
        destination = (
            self.output
            / "test-sha256_run1_candidate1.pdf"
        )

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"existing user data")

        with patch.object(
            engine.qpdf,
            "verify_unlocked",
            return_value=qpdf.QPDFResult("invalid_output"),
        ), patch.object(
            engine.qpdf,
            "decrypt_pdf",
        ) as decrypt_mock:
            result = self.call_engine()

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "output_path_conflict")
        self.assertEqual(destination.read_bytes(), b"existing user data")
        decrypt_mock.assert_not_called()
        engine.fail_rule_run.assert_called_once_with(
            self.database, 1, "output_path_conflict"
        )
        engine.record_candidate_attempt.assert_not_called()


    def test_invalid_completed_output_starts_fresh_recovery_run(self):
        old_output = (
            self.output
            / "test-sha256_run1_candidate1.pdf"
        )
        old_output.parent.mkdir(parents=True, exist_ok=True)
        old_output.write_bytes(b"preserve historical output")

        completed_details = {
            "run": {
                "run_id": 1,
                "sha256": "test-sha256",
                "outcome": "success",
                "attempted_count": 1,
            },
            "attempts": [
                {
                    "candidate_number": 1,
                    "result": "success",
                }
            ],
        }

        recovery_details = {
            "run": {
                "run_id": 2,
                "sha256": "test-sha256",
                "outcome": "running",
                "attempted_count": 0,
            },
            "attempts": [],
        }

        engine.start_rule_run.side_effect = [
            {
                "status": "already_completed",
                "run_id": 1,
                "outcome": "success",
                "attempted_candidates": [1],
            },
            {
                "status": "created",
                "run_id": 2,
                "outcome": "running",
                "attempted_candidates": [],
            },
        ]

        engine.get_rule_run.side_effect = [
            completed_details,
            recovery_details,
        ]

        with patch.object(
            engine.qpdf,
            "verify_unlocked",
            return_value=qpdf.QPDFResult("invalid_output"),
        ), patch.object(
            engine.qpdf,
            "decrypt_pdf",
            return_value=qpdf.QPDFResult(
                "unlocked",
                output_path=str(
                    self.output / "test-sha256_run2_candidate1.pdf"
                ),
                output_sha256="recovery-output-sha256",
            ),
        ):
            result = self.call_engine()

        self.assertEqual(result["status"], "unlocked")
        self.assertEqual(result["run_id"], 2)
        self.assertEqual(result["attempted_count"], 1)

        # The previous output must not be overwritten or deleted.
        self.assertEqual(
            old_output.read_bytes(),
            b"preserve historical output",
        )

        self.assertEqual(engine.start_rule_run.call_count, 2)
        self.assertTrue(
            engine.start_rule_run.call_args_list[1].kwargs[
                "retry_completed_success"
            ]
        )

        engine.record_candidate_attempt.assert_called_once_with(
            self.database,
            2,
            1,
            "fingerprint-one",
            "success",
        )


    def test_missing_completed_output_starts_fresh_recovery_run(self):
        completed_details = {
            "run": {
                "run_id": 1,
                "sha256": "test-sha256",
                "outcome": "success",
                "attempted_count": 1,
            },
            "attempts": [
                {
                    "candidate_number": 1,
                    "result": "success",
                }
            ],
        }

        recovery_details = {
            "run": {
                "run_id": 2,
                "sha256": "test-sha256",
                "outcome": "running",
                "attempted_count": 0,
            },
            "attempts": [],
        }

        engine.start_rule_run.side_effect = [
            {
                "status": "already_completed",
                "run_id": 1,
                "outcome": "success",
                "attempted_candidates": [1],
            },
            {
                "status": "created",
                "run_id": 2,
                "outcome": "running",
                "attempted_candidates": [],
            },
        ]

        engine.get_rule_run.side_effect = [
            completed_details,
            recovery_details,
        ]

        expected_output = (
            self.output / "test-sha256_run2_candidate1.pdf"
        )

        with patch.object(
            engine.qpdf,
            "verify_unlocked",
        ) as verify_mock, patch.object(
            engine.qpdf,
            "decrypt_pdf",
            return_value=qpdf.QPDFResult(
                "unlocked",
                output_path=str(expected_output),
                output_sha256="recovered-output-sha256",
            ),
        ) as decrypt_mock:
            result = self.call_engine()

        self.assertEqual(result["status"], "unlocked")
        self.assertEqual(result["run_id"], 2)
        self.assertEqual(result["output_path"], str(expected_output))
        self.assertEqual(result["attempted_count"], 1)

        # Missing historical output must not be verified or overwritten.
        verify_mock.assert_not_called()
        decrypt_mock.assert_called_once()

        decrypt_args = decrypt_mock.call_args
        self.assertEqual(Path(decrypt_args.args[1]), expected_output)
        self.assertEqual(decrypt_args.args[2], "synthetic-password-one")

        self.assertEqual(engine.start_rule_run.call_count, 2)
        self.assertTrue(
            engine.start_rule_run.call_args_list[1].kwargs[
                "retry_completed_success"
            ]
        )

        engine.record_candidate_attempt.assert_called_once_with(
            self.database,
            2,
            1,
            "fingerprint-one",
            "success",
        )

    def test_candidate_passwords_are_not_saved_in_tracker(self):
        with patch.object(
            engine.qpdf,
            "decrypt_pdf",
            return_value=qpdf.QPDFResult("wrong_password"),
        ):
            self.call_engine()

        recorded = str(
            engine.record_candidate_attempt.call_args_list
        )

        self.assertNotIn("synthetic-password-one", recorded)
        self.assertNotIn("synthetic-password-two", recorded)


if __name__ == "__main__":
    unittest.main()
