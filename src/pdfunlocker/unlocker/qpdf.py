"""Safe QPDF adapter for PDF Unlocker.

Passwords are passed through short-lived, permission-restricted files.
They are never included in command arguments, logs, or database records.
"""

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


CHUNK_SIZE = 1024 * 1024


@dataclass
class QPDFResult:
    status: str
    returncode: int | None = None
    output_path: str | None = None
    output_sha256: str | None = None
    error_code: str | None = None


class QPDFError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def find_qpdf():
    executable = shutil.which("qpdf")
    if not executable:
        raise QPDFError("qpdf_missing", "QPDF executable was not found.")
    return executable


def _run(args, timeout=120):
    try:
        return subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise QPDFError("qpdf_timeout", "QPDF operation timed out.") from exc
    except OSError as exc:
        raise QPDFError("qpdf_execution_error", "Unable to execute QPDF.") from exc


def calculate_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _password_file(password, directory):
    if not isinstance(password, str):
        raise ValueError("Password must be a string.")

    if "\n" in password or "\r" in password or "\0" in password:
        raise ValueError("Password contains unsupported control characters.")

    path = Path(directory) / "password.txt"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )

    with os.fdopen(descriptor, "wb") as handle:
        handle.write(password.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())

    return path


def detect_encryption(pdf_path, timeout=120):
    """Return encrypted, not_encrypted, or uncertain."""
    path = Path(pdf_path)

    if not path.is_file() or path.stat().st_size == 0:
        return QPDFResult("corrupted", error_code="missing_or_empty_file")

    executable = find_qpdf()
    result = _run(
        [executable, "--is-encrypted", str(path)],
        timeout=timeout,
    )

    if result.returncode == 0:
        return QPDFResult("encrypted", returncode=0)

    if result.returncode == 2:
        return QPDFResult("not_encrypted", returncode=2)

    return QPDFResult("uncertain", returncode=result.returncode,
                      error_code="encryption_detection_failed")


def verify_unlocked(pdf_path, timeout=120):
    """Verify that a PDF is readable and no longer encrypted."""
    path = Path(pdf_path)

    if not path.is_file() or path.stat().st_size == 0:
        return QPDFResult("invalid_output", error_code="missing_or_empty_output")

    executable = find_qpdf()

    encryption = _run(
        [executable, "--is-encrypted", str(path)],
        timeout=timeout,
    )

    if encryption.returncode == 0:
        return QPDFResult("still_encrypted", returncode=0)

    if encryption.returncode != 2:
        return QPDFResult(
            "uncertain",
            returncode=encryption.returncode,
            error_code="output_encryption_check_failed",
        )

    check = _run(
        [executable, "--check", str(path)],
        timeout=timeout,
    )

    if check.returncode == 0:
        return QPDFResult(
            "verified",
            returncode=0,
            output_path=str(path),
            output_sha256=calculate_sha256(path),
        )

    if check.returncode == 3:
        return QPDFResult(
            "review",
            returncode=3,
            error_code="qpdf_validation_warnings",
        )

    return QPDFResult(
        "invalid_output",
        returncode=check.returncode,
        error_code="qpdf_output_validation_failed",
    )


def decrypt_pdf(input_path, output_path, password, timeout=120):
    """Attempt one password and verify the decrypted output."""
    source = Path(input_path)
    destination = Path(output_path)

    if not source.is_file():
        raise FileNotFoundError("Input PDF does not exist.")

    if destination.exists():
        raise FileExistsError("Output path already exists; refusing to overwrite.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    executable = find_qpdf()

    with tempfile.TemporaryDirectory(prefix="pdfunlocker-qpdf-") as temp:
        os.chmod(temp, 0o700)
        password_path = _password_file(password, temp)

        result = _run(
            [
                executable,
                f"--password-file={password_path}",
                "--decrypt",
                str(source),
                str(destination),
            ],
            timeout=timeout,
        )

    if result.returncode != 0:
        destination.unlink(missing_ok=True)

        diagnostic = (result.stderr or "").lower()

        if "invalid password" in diagnostic or "password" in diagnostic:
            return QPDFResult(
                "wrong_password",
                returncode=result.returncode,
                error_code="password_rejected",
            )

        if result.returncode == 3:
            return QPDFResult(
                "review",
                returncode=3,
                error_code="qpdf_decryption_warning",
            )

        return QPDFResult(
            "error",
            returncode=result.returncode,
            error_code="qpdf_decryption_failed",
        )

    verification = verify_unlocked(destination, timeout=timeout)

    if verification.status != "verified":
        destination.unlink(missing_ok=True)
        return verification

    return QPDFResult(
        "unlocked",
        returncode=result.returncode,
        output_path=str(destination),
        output_sha256=verification.output_sha256,
    )
