from concurrent.futures import ThreadPoolExecutor

from pdfunlocker.database import manager


def _add_pdf(monkeypatch, tmp_path, *, status="pending"):
    db_path = tmp_path / "pdfunlocker.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)
    pdf_id = manager.add_pdf(
        filename="sample.pdf",
        source_path="/tmp/sample.pdf",
        sha256=f"hash-{status}-{id(tmp_path)}",
    )
    assert pdf_id is not None
    if status != "pending":
        manager.update_status(pdf_id, status)
    return pdf_id


def test_claim_pdf_changes_pending_to_processing(monkeypatch, tmp_path):
    pdf_id = _add_pdf(monkeypatch, tmp_path)

    assert manager.claim_pdf(pdf_id) is True

    record = manager.get_pdf_by_id(pdf_id)
    assert record["status"] == "processing"
    assert record["processed_at"] is None
    assert record["error"] is None


def test_claim_pdf_cannot_claim_same_record_twice(monkeypatch, tmp_path):
    pdf_id = _add_pdf(monkeypatch, tmp_path)

    assert manager.claim_pdf(pdf_id) is True
    assert manager.claim_pdf(pdf_id) is False


def test_failed_pdf_requires_explicit_retry(monkeypatch, tmp_path):
    pdf_id = _add_pdf(monkeypatch, tmp_path, status="failed")

    assert manager.claim_pdf(pdf_id) is False
    assert manager.get_pdf_by_id(pdf_id)["status"] == "failed"

    assert manager.claim_pdf(pdf_id, retry_failed=True) is True
    assert manager.get_pdf_by_id(pdf_id)["status"] == "processing"


def test_claim_pdf_returns_false_for_unknown_id(monkeypatch, tmp_path):
    _add_pdf(monkeypatch, tmp_path)

    assert manager.claim_pdf(999999) is False


def test_concurrent_claims_allow_exactly_one_winner(monkeypatch, tmp_path):
    pdf_id = _add_pdf(monkeypatch, tmp_path)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(manager.claim_pdf, [pdf_id, pdf_id]))

    assert sorted(results) == [False, True]
    assert manager.get_pdf_by_id(pdf_id)["status"] == "processing"
