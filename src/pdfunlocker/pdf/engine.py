from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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
        result = _run_qpdf([
            f"--password={password}",
            "--check",
            str(path),
        ])
    except (subprocess.TimeoutExpired, OSError):
        return False

    return result.returncode in QPDF_SUCCESS_CODES


def unlock_pdf(
    path: Path,
    password: str,
    output_path: Path,
) -> PDFUnlockResult:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = _run_qpdf([
            f"--password={password}",
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
