import subprocess

from pdfunlocker.pdf import scanner
from pdfunlocker.pdf.engine import QPDF_TIMEOUT_SECONDS


def test_validate_pdf_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("qpdf", QPDF_TIMEOUT_SECONDS)

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)

    assert scanner.validate_pdf(tmp_path / "sample.pdf") == (False, False)


def test_validate_pdf_missing_qpdf(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("qpdf")

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)

    assert scanner.validate_pdf(tmp_path / "sample.pdf") == (False, False)


def test_validate_pdf_uses_shared_timeout(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(scanner.subprocess, "run", fake_run)

    assert scanner.validate_pdf(tmp_path / "sample.pdf") == (True, False)
    assert captured["timeout"] == QPDF_TIMEOUT_SECONDS
