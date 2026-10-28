import pytest
from pdfunlocker.database import manager


@pytest.mark.parametrize("status", ["locked", "corrupted"])
def test_new_statuses_are_accepted_in_isolated_database(tmp_path, monkeypatch, status):
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setattr(manager, "database_path", lambda: db_path)
    manager.initialize_database()
    pdf_id = manager.add_pdf(
        filename="sample.pdf",
        source_path=str(tmp_path / "sample.pdf"),
        sha256=("a" if status == "locked" else "b") * 64,
    )
    assert pdf_id is not None
    manager.update_status(pdf_id, status)
