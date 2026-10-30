import subprocess

from pdfunlocker.pdf import engine


def completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["qpdf"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def test_check_pdf_accepts_qpdf_warning_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine,
        "_run_qpdf",
        lambda args: completed(3, stderr="operation completed with warnings"),
    )

    result = engine.check_pdf(tmp_path / "sample.pdf")

    assert result.success
    assert not result.encrypted
    assert result.error is None


def test_try_password_accepts_qpdf_warning_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine,
        "_run_qpdf",
        lambda args: completed(3, stderr="operation completed with warnings"),
    )

    assert engine.try_password(tmp_path / "sample.pdf", "test-password")


def test_unlock_pdf_accepts_qpdf_warning_exit_code(monkeypatch, tmp_path):
    output = tmp_path / "output" / "sample.pdf"

    def fake_run(args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF-test-output")
        return completed(3, stderr="operation completed with warnings")

    monkeypatch.setattr(engine, "_run_qpdf", fake_run)

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "test-password",
        output,
    )

    assert result.success
    assert result.output_path == output
    assert output.is_file()


def test_check_pdf_still_detects_encrypted_pdf(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine,
        "_run_qpdf",
        lambda args: completed(2, stderr="File is encrypted; password required"),
    )

    result = engine.check_pdf(tmp_path / "sample.pdf")

    assert not result.success
    assert result.encrypted
    assert result.error == "PDF is encrypted"


def test_check_pdf_rejects_qpdf_error_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine,
        "_run_qpdf",
        lambda args: completed(2, stderr="file is damaged"),
    )

    result = engine.check_pdf(tmp_path / "sample.pdf")

    assert not result.success
    assert not result.encrypted


def test_try_password_rejects_qpdf_error_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(
        engine,
        "_run_qpdf",
        lambda args: completed(2, stderr="incorrect password"),
    )

    assert not engine.try_password(tmp_path / "sample.pdf", "wrong")


def test_unlock_pdf_rejects_qpdf_error_and_removes_partial_output(
    monkeypatch,
    tmp_path,
):
    output = tmp_path / "output" / "sample.pdf"

    def fake_run(args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"partial output")
        return completed(2, stderr="decryption failed")

    monkeypatch.setattr(engine, "_run_qpdf", fake_run)

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "test-password",
        output,
    )

    assert not result.success
    assert not output.exists()
