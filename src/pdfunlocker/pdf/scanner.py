from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from pdfunlocker.database.manager import add_pdf, get_pdf_by_hash
from pdfunlocker.pdf.engine import QPDF_TIMEOUT_SECONDS


CHUNK_SIZE = 1024 * 1024


def calculate_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)

    return digest.hexdigest()


def validate_pdf(path: Path) -> tuple[bool, bool]:
    """Return (readable, encrypted)."""
    try:
        result = subprocess.run(
            ["qpdf", "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=QPDF_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False, False

    combined = f"{result.stdout}\n{result.stderr}".lower()

    markers = (
        "invalid password",
        "password required",
        "requires a password",
        "incorrect password",
        "file is encrypted",
        "is encrypted",
        "encrypted file",
        "encryption key",
    )

    if any(marker in combined for marker in markers):
        return True, True

    # qpdf exit code 0 means no warnings or errors.
    # Exit code 3 means warnings were reported, but processing succeeded.
    # Exit code 2 indicates errors and is not accepted as readable here.
    if result.returncode in (0, 3):
        return True, False

    return False, False


def scan_directory(inbox: Path) -> dict[str, int]:
    if not inbox.exists():
        raise FileNotFoundError(
            f"Inbox directory does not exist: {inbox}"
        )

    if not inbox.is_dir():
        raise NotADirectoryError(
            f"Inbox path is not a directory: {inbox}"
        )

    result = {
        "total": 0,
        "new": 0,
        "duplicate": 0,
        "invalid": 0,
        "encrypted": 0,
        "skipped": 0,
        "corrupted": 0,
    }

    from pdfunlocker.database.manager import update_status

    for path in sorted(inbox.iterdir()):
        if not path.is_file() or path.suffix.lower() != ".pdf":
            continue

        result["total"] += 1

        try:
            sha256 = calculate_sha256(path)
        except OSError:
            result["invalid"] += 1
            result["corrupted"] += 1
            continue

        if get_pdf_by_hash(sha256) is not None:
            result["duplicate"] += 1
            continue

        readable, encrypted = validate_pdf(path)

        pdf_id = add_pdf(
            filename=path.name,
            source_path=str(path),
            sha256=sha256,
        )

        if pdf_id is None:
            result["duplicate"] += 1
            continue

        if not readable:
            result["invalid"] += 1
            result["corrupted"] += 1

            update_status(
                pdf_id,
                "corrupted",
                error="PDF validation failed; file may be corrupted or unreadable",
            )
            continue

        result["new"] += 1

        if encrypted:
            result["encrypted"] += 1
        else:
            result["skipped"] += 1
            update_status(pdf_id, "skipped")

    return result
