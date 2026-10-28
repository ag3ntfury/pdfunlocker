import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.pdf.scanner import validate_pdf


class ScannerValidationTests(unittest.TestCase):
    def run_qpdf(self, returncode, stdout="", stderr=""):
        return patch(
            "pdfunlocker.pdf.scanner.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["qpdf"], returncode=returncode,
                stdout=stdout, stderr=stderr
            ),
        )

    def test_valid_unencrypted_pdf(self):
        with self.run_qpdf(0, stdout="PDF is not encrypted"):
            self.assertEqual(validate_pdf(Path("sample.pdf")), (True, False))

    def test_invalid_password_means_encrypted_pdf(self):
        with self.run_qpdf(2, stderr="qpdf: invalid password"):
            self.assertEqual(validate_pdf(Path("sample.pdf")), (True, True))

    def test_password_required_means_encrypted_pdf(self):
        with self.run_qpdf(2, stderr="PDF file is encrypted; password required"):
            self.assertEqual(validate_pdf(Path("sample.pdf")), (True, True))

    def test_corrupted_pdf_is_invalid(self):
        with self.run_qpdf(2, stderr="file is damaged"):
            self.assertEqual(validate_pdf(Path("sample.pdf")), (False, False))


if __name__ == "__main__":
    unittest.main()


class ScannerDatabaseClassificationTests(unittest.TestCase):
    def test_scan_records_corrupt_pdf_as_failed(self):
        import tempfile
        from unittest.mock import patch
        from pdfunlocker.pdf import scanner

        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory)
            pdf = inbox / "damaged.pdf"
            pdf.write_bytes(b"%PDF-test-corrupt")

            with patch.object(scanner, "get_pdf_by_hash", return_value=None), \
                 patch.object(scanner, "validate_pdf", return_value=(False, False)), \
                 patch.object(scanner, "add_pdf", return_value=42) as add_pdf, \
                 patch("pdfunlocker.database.manager.update_status") as update_status:
                result = scanner.scan_directory(inbox)

            self.assertEqual(result["invalid"], 1)
            self.assertEqual(result["new"], 0)
            add_pdf.assert_called_once()
            update_status.assert_called_once_with(
                42,
                "corrupted",
                error="PDF validation failed; file may be corrupted or unreadable",
            )

    def test_scan_keeps_encrypted_pdf_eligible_for_unlocking(self):
        import tempfile
        from unittest.mock import patch
        from pdfunlocker.pdf import scanner

        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory)
            pdf = inbox / "locked.pdf"
            pdf.write_bytes(b"%PDF-test-encrypted")

            with patch.object(scanner, "get_pdf_by_hash", return_value=None), \
                 patch.object(scanner, "validate_pdf", return_value=(True, True)), \
                 patch.object(scanner, "add_pdf", return_value=43), \
                 patch("pdfunlocker.database.manager.update_status") as update_status:
                result = scanner.scan_directory(inbox)

            self.assertEqual(result["new"], 1)
            self.assertEqual(result["invalid"], 0)
            update_status.assert_not_called()


    def test_scan_marks_unencrypted_pdf_as_skipped(self):
        import tempfile
        from unittest.mock import patch
        from pdfunlocker.pdf import scanner

        with tempfile.TemporaryDirectory() as directory:
            inbox = Path(directory)
            pdf = inbox / "plain.pdf"
            pdf.write_bytes(b"%PDF-test-plain")

            patch_hash = patch.object(scanner, "get_pdf_by_hash", return_value=None)
            patch_validation = patch.object(scanner, "validate_pdf", return_value=(True, False))
            patch_add = patch.object(scanner, "add_pdf", return_value=44)
            patch_status = patch("pdfunlocker.database.manager.update_status")

            with patch_hash, patch_validation, patch_add, patch_status as update_status:
                result = scanner.scan_directory(inbox)

            self.assertEqual(result["new"], 1)
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(result["encrypted"], 0)
            update_status.assert_called_once_with(44, "skipped")
