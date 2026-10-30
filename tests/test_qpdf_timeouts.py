import subprocess

from pdfunlocker.pdf import engine


def test_check_pdf_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("qpdf", 60)

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    result = engine.check_pdf(tmp_path / "sample.pdf")

    assert not result.success
    assert not result.encrypted
    assert "timed out" in result.error.lower()


def test_check_pdf_missing_qpdf(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("qpdf")

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    result = engine.check_pdf(tmp_path / "sample.pdf")

    assert not result.success
    assert "unavailable" in result.error.lower()


def test_try_password_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired("qpdf", 60)

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine.try_password(tmp_path / "sample.pdf", "test") is False


def test_unlock_pdf_timeout_removes_partial_file(monkeypatch, tmp_path):
    output = tmp_path / "output" / "sample.pdf"

    def fake_run(*args, **kwargs):
        output.write_bytes(b"partial output")
        raise subprocess.TimeoutExpired("qpdf", 60)

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "test",
        output,
    )

    assert not result.success
    assert "timed out" in result.error.lower()
    assert not output.exists()


def test_unlock_pdf_failure_removes_partial_file(monkeypatch, tmp_path):
    output = tmp_path / "output" / "sample.pdf"

    def fake_run(*args, **kwargs):
        output.write_bytes(b"partial output")
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=2,
            stdout="",
            stderr="error",
        )

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "test",
        output,
    )

    assert not result.success
    assert not output.exists()


def test_qpdf_timeout_is_passed_to_subprocess(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    engine.check_pdf(tmp_path / "sample.pdf")

    assert captured["timeout"] == engine.QPDF_TIMEOUT_SECONDS
