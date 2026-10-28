from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


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


def check_pdf(path: Path) -> PDFCheckResult:
    result = subprocess.run(
        ["qpdf", "--check", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        return PDFCheckResult(
            success=True,
            encrypted=False,
        )

    combined = f"{result.stdout}\n{result.stderr}".lower()

    if "password" in combined or "encrypted" in combined:
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
    result = subprocess.run(
        [
            "qpdf",
            f"--password={password}",
            "--check",
            str(path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    return result.returncode == 0


def unlock_pdf(
    path: Path,
    password: str,
    output_path: Path,
) -> PDFUnlockResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [
            "qpdf",
            f"--password={password}",
            "--decrypt",
            str(path),
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass

        return PDFUnlockResult(
            success=False,
            error="PDF unlock failed",
        )

    return PDFUnlockResult(
        success=True,
        output_path=output_path,
    )
