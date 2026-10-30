from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


# Maximum time allowed for each individual QPDF operation.
QPDF_TIMEOUT_SECONDS = 60

# QPDF exit code 3 means warnings occurred, but processing succeeded.
QPDF_SUCCESS_CODES = (0, 3)


@dataclass(frozen=True)
class PDFCheckResult:
    success: bool
    encrypted: bool
    error: str | None = None


@dataclass(frozen=True)
class PDFUnlockResult:
    success: bool
    output_path: Path | None = None
    error: str | None = None


@contextmanager
def _temporary_password_file(password: str) -> Iterator[Path]:
    """Provide QPDF a private password file without exposing the secret in argv."""
    if "\n" in password or "\r" in password:
        raise ValueError("QPDF password files cannot represent newline characters")

    fd, filename = tempfile.mkstemp(prefix="pdfunlocker-qpdf-password-")
    password_path = Path(filename)

    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            fd = -1
            stream.write(password)
            stream.write("\n")

        yield password_path
    finally:
        if fd >= 0:
            os.close(fd)
        password_path.unlink(missing_ok=True)


def _run_qpdf(args: list[str]) -> subprocess.CompletedProcess:
    """Run QPDF with a fixed timeout and no shell interpretation."""
    return subprocess.run(
        ["qpdf", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=QPDF_TIMEOUT_SECONDS,
    )


def check_pdf(path: Path) -> PDFCheckResult:
    try:
        result = _run_qpdf(["--check", str(path)])
    except subprocess.TimeoutExpired:
        return PDFCheckResult(
            success=False,
            encrypted=False,
            error=f"QPDF operation timed out after {QPDF_TIMEOUT_SECONDS} seconds",
        )
    except OSError:
        return PDFCheckResult(
            success=False,
            encrypted=False,
            error="QPDF is unavailable or could not be executed",
        )

    if result.returncode in QPDF_SUCCESS_CODES:
        return PDFCheckResult(success=True, encrypted=False)

    combined = f"{result.stdout}\n{result.stderr}".lower()

    encryption_markers = (
        "invalid password",
        "password required",
        "requires a password",
        "incorrect password",
        "file is encrypted",
        "is encrypted",
        "encrypted file",
        "encryption key",
    )

    if any(marker in combined for marker in encryption_markers):
        return PDFCheckResult(
            success=False,
            encrypted=True,
            error="PDF is encrypted",
        )

    return PDFCheckResult(
        success=False,
        encrypted=False,
        error="PDF validation failed",
    )


def try_password(path: Path, password: str) -> bool:
    try:
        with _temporary_password_file(password) as password_path:
            result = _run_qpdf([
                f"--password-file={password_path}",
                "--check",
                str(path),
            ])
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return False

    return result.returncode in QPDF_SUCCESS_CODES


def unlock_pdf(
    path: Path,
    password: str,
    output_path: Path,
) -> PDFUnlockResult:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with _temporary_password_file(password) as password_path:
            result = _run_qpdf([
                f"--password-file={password_path}",
                "--decrypt",
                str(path),
                str(output_path),
            ])

        if result.returncode not in QPDF_SUCCESS_CODES:
            raise RuntimeError("QPDF decryption failed")

        return PDFUnlockResult(
            success=True,
            output_path=output_path,
        )

    except subprocess.TimeoutExpired:
        error = (
            f"QPDF operation timed out after "
            f"{QPDF_TIMEOUT_SECONDS} seconds"
        )
    except OSError:
        error = "QPDF is unavailable or could not be executed"
    except ValueError:
        error = "Password contains unsupported newline characters"
    except RuntimeError:
        error = "PDF unlock failed"

    try:
        output_path.unlink(missing_ok=True)
    except OSError:
        pass

    return PDFUnlockResult(
        success=False,
        error=error,
    )
