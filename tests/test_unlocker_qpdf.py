import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pdfunlocker.unlocker import qpdf


def make_nonempty_file():
    handle = tempfile.NamedTemporaryFile(delete=False)
    handle.write(b"%PDF-1.4\n% Test fixture\n")
    handle.close()
    return Path(handle.name)


class QPDFAdapterTests(unittest.TestCase):

    def test_password_file_is_private_and_contains_password(self):
        with tempfile.TemporaryDirectory() as directory:
            path = qpdf._password_file("test123", directory)
            self.assertEqual(path.read_text(), "test123")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_password_file_rejects_newlines(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                qpdf._password_file("bad\npassword", directory)

    def test_encryption_detection_encrypted(self):
        fake = type("Result", (), {"returncode": 0})()
        path = make_nonempty_file()
        try:
            with patch.object(qpdf, "find_qpdf", return_value="qpdf"), \
                 patch.object(qpdf, "_run", return_value=fake):
                result = qpdf.detect_encryption(path)
            self.assertEqual(result.status, "encrypted")
        finally:
            path.unlink(missing_ok=True)

    def test_encryption_detection_not_encrypted(self):
        fake = type("Result", (), {"returncode": 2})()
        path = make_nonempty_file()
        try:
            with patch.object(qpdf, "find_qpdf", return_value="qpdf"), \
                 patch.object(qpdf, "_run", return_value=fake):
                result = qpdf.detect_encryption(path)
            self.assertEqual(result.status, "not_encrypted")
        finally:
            path.unlink(missing_ok=True)

    def test_encryption_detection_uncertain(self):
        fake = type("Result", (), {"returncode": 1})()
        path = make_nonempty_file()
        try:
            with patch.object(qpdf, "find_qpdf", return_value="qpdf"), \
                 patch.object(qpdf, "_run", return_value=fake):
                result = qpdf.detect_encryption(path)
            self.assertEqual(result.status, "uncertain")
        finally:
            path.unlink(missing_ok=True)

    def test_verification_rejects_encrypted_output(self):
        encrypted = type("Result", (), {"returncode": 0})()
        path = make_nonempty_file()
        try:
            with patch.object(qpdf, "find_qpdf", return_value="qpdf"), \
                 patch.object(qpdf, "_run", return_value=encrypted):
                result = qpdf.verify_unlocked(path)
            self.assertEqual(result.status, "still_encrypted")
        finally:
            path.unlink(missing_ok=True)

    def test_verification_accepts_valid_unencrypted_output(self):
        responses = [
            type("Result", (), {"returncode": 2})(),
            type("Result", (), {"returncode": 0})(),
        ]
        path = make_nonempty_file()
        try:
            with patch.object(qpdf, "find_qpdf", return_value="qpdf"), \
                 patch.object(qpdf, "_run", side_effect=responses):
                result = qpdf.verify_unlocked(path)
            self.assertEqual(result.status, "verified")
            self.assertIsNotNone(result.output_sha256)
        finally:
            path.unlink(missing_ok=True)

    def test_validation_warning_goes_to_review(self):
        responses = [
            type("Result", (), {"returncode": 2})(),
            type("Result", (), {"returncode": 3})(),
        ]
        path = make_nonempty_file()
        try:
            with patch.object(qpdf, "find_qpdf", return_value="qpdf"), \
                 patch.object(qpdf, "_run", side_effect=responses):
                result = qpdf.verify_unlocked(path)
            self.assertEqual(result.status, "review")
        finally:
            path.unlink(missing_ok=True)

    def test_missing_pdf_is_corrupted(self):
        result = qpdf.detect_encryption(
            "/path/that/does/not/exist.pdf"
        )
        self.assertEqual(result.status, "corrupted")


if __name__ == "__main__":
    unittest.main()
