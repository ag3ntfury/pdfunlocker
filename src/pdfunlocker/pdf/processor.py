from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from pdfunlocker.database.manager import get_pdf_by_id, update_status
from pdfunlocker.pdf.engine import try_password, unlock_pdf


def process_pdf(
    pdf_id: int,
    password: str,
    *,
    original_directory: Path,
    unlocked_directory: Path,
) -> bool:
    record = get_pdf_by_id(pdf_id)

    if record is None:
        raise ValueError(f"PDF record not found: {pdf_id}")

    source_path = Path(record["source_path"])
    filename = record["filename"]

    if not source_path.exists():
        update_status(
            pdf_id,
            "failed",
            error="Source PDF does not exist",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        return False

    original_directory.mkdir(parents=True, exist_ok=True)
    unlocked_directory.mkdir(parents=True, exist_ok=True)

    original_path = original_directory / filename
    unlocked_path = unlocked_directory / filename

    update_status(
        pdf_id,
        "processing",
        error=None,
    )

    previous_attempts = int(record["attempt_count"] or 0)
    attempt_count = previous_attempts + 1

    if not try_password(source_path, password):
        update_status(
            pdf_id,
            "failed",
            attempt_count=attempt_count,
            error="Password attempt failed",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        return False

    unlock_result = unlock_pdf(
        source_path,
        password,
        unlocked_path,
    )

    if not unlock_result.success:
        update_status(
            pdf_id,
            "failed",
            attempt_count=attempt_count,
            error=unlock_result.error or "PDF unlock failed",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        return False

    try:
        if original_path.exists():
            original_path.unlink()

        shutil.move(str(source_path), str(original_path))
    except OSError as exc:
        try:
            unlocked_path.unlink(missing_ok=True)
        except OSError:
            pass

        update_status(
            pdf_id,
            "failed",
            attempt_count=attempt_count,
            error="Failed to move original PDF",
            processed_at=datetime.now(timezone.utc).isoformat(),
        )
        return False

    update_status(
        pdf_id,
        "unlocked",
        original_path=str(original_path),
        unlocked_path=str(unlocked_path),
        attempt_count=attempt_count,
        processed_at=datetime.now(timezone.utc).isoformat(),
        error=None,
    )

    return True
