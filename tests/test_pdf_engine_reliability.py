import os
import stat
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


def test_try_password_uses_private_password_file_and_cleans_it(
    monkeypatch,
    tmp_path,
):
    password = "secret with spaces ü"
    observed = {}

    def fake_run(args):
        observed["args"] = args
        password_arg = next(
            arg for arg in args if arg.startswith("--password-file=")
        )
        password_path = password_arg.split("=", 1)[1]
        observed["path"] = password_path
        observed["content"] = open(
            password_path,
            encoding="utf-8",
        ).read()
        observed["mode"] = stat.S_IMODE(os.stat(password_path).st_mode)
        return completed(0)

    monkeypatch.setattr(engine, "_run_qpdf", fake_run)

    assert engine.try_password(tmp_path / "sample.pdf", password)

    assert password not in observed["args"]
    assert observed["content"] == password + "\n"
    assert observed["mode"] == 0o600
    assert not os.path.exists(observed["path"])


def test_unlock_pdf_cleans_password_file_after_success(
    monkeypatch,
    tmp_path,
):
    output = tmp_path / "output" / "sample.pdf"
    observed = {}

    def fake_run(args):
        password_arg = next(
            arg for arg in args if arg.startswith("--password-file=")
        )
        password_path = password_arg.split("=", 1)[1]
        observed["path"] = password_path
        observed["args"] = args
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF-test-output")
        return completed(0)

    monkeypatch.setattr(engine, "_run_qpdf", fake_run)

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "private-password",
        output,
    )

    assert result.success
    assert "private-password" not in observed["args"]
    assert not os.path.exists(observed["path"])


def test_password_file_is_cleaned_after_qpdf_timeout(monkeypatch, tmp_path):
    observed = {}

    def fake_run(args):
        password_arg = next(
            arg for arg in args if arg.startswith("--password-file=")
        )
        password_path = password_arg.split("=", 1)[1]
        observed["path"] = password_path
        raise subprocess.TimeoutExpired("qpdf", 60)

    monkeypatch.setattr(engine, "_run_qpdf", fake_run)

    assert not engine.try_password(tmp_path / "sample.pdf", "secret")
    assert not os.path.exists(observed["path"])


def test_unlock_pdf_cleans_password_file_after_qpdf_timeout(
    monkeypatch,
    tmp_path,
):
    output = tmp_path / "output" / "sample.pdf"
    observed = {}

    def fake_run(args):
        password_arg = next(
            arg for arg in args if arg.startswith("--password-file=")
        )
        observed["path"] = password_arg.split("=", 1)[1]
        raise subprocess.TimeoutExpired("qpdf", 60)

    monkeypatch.setattr(engine, "_run_qpdf", fake_run)

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "secret",
        output,
    )

    assert not result.success
    assert not os.path.exists(observed["path"])
    assert not output.exists()


def test_password_with_newline_is_rejected_without_running_qpdf(
    monkeypatch,
    tmp_path,
):
    def unexpected_run(args):
        raise AssertionError("QPDF must not run for newline-containing passwords")

    monkeypatch.setattr(engine, "_run_qpdf", unexpected_run)

    assert not engine.try_password(tmp_path / "sample.pdf", "line1\nline2")

    result = engine.unlock_pdf(
        tmp_path / "sample.pdf",
        "line1\nline2",
        tmp_path / "output.pdf",
    )

    assert not result.success
    assert result.error == "Password contains unsupported newline characters"
