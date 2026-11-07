"""Authenticated encryption for full payment-card numbers stored in profiles.

The AES-256-GCM key is held in a separate mode-0600 file under the private
application directory. Ciphertext is stored in SQLite and profile exports.
Only the password-rule candidate resolver decrypts values when required.
"""
from __future__ import annotations

import base64
import errno
import os
import re
import secrets
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pdfunlocker.paths import APP_DIR


KEY_PATH = APP_DIR / "config" / "card-number.key"
TOKEN_PREFIX = "ENCv1:"
_AAD = b"PDFUnlocker:card-number:v1"
_BANK_CARD_RE = re.compile(r"^BANK_1[2-6][0-9]{2}F$")
_REPEATABLE_RE = re.compile(r"^(.*)_([0-9]+)$")


class CardEncryptionError(RuntimeError):
    """Raised when card ciphertext cannot be authenticated or decrypted."""


def is_card_field_key(field_key: str) -> bool:
    key = str(field_key).upper()
    match = _REPEATABLE_RE.fullmatch(key)
    base = match.group(1) if match else key
    return base in {
        "CARD_NO",
        "CARD_NUMBER",
        "CREDIT_CARD_NUMBER",
    } or bool(_BANK_CARD_RE.fullmatch(base))


def is_encrypted_card(value: str) -> bool:
    return isinstance(value, str) and value.startswith(TOKEN_PREFIX)


def is_masked_card(value: str) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"X{8,15}[0-9]{4}", value)
    )


@contextmanager
def _key_file_lock():
    """Serialize key creation and recovery across independent processes."""
    lock_path = KEY_PATH.with_name(KEY_PATH.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    fd = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT,
        0o600,
    )

    locked = False
    windows_lock = False

    try:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass

        if os.name == "nt":
            import msvcrt

            windows_lock = True

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")

            while True:
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if exc.errno not in (
                        errno.EACCES,
                        errno.EDEADLK,
                        errno.EAGAIN,
                    ):
                        raise
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
            locked = True

        yield

    finally:
        if locked:
            if windows_lock:
                import msvcrt

                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)

        os.close(fd)


def _write_private_key(path: Path, data: bytes) -> None:
    """Atomically write a private key using a unique temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)

    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass

        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(temp_path, path)

        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    finally:
        if fd >= 0:
            os.close(fd)

        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _load_or_create_key() -> bytes:
    """Load, restore, or create one consistent key under an inter-process lock."""
    with _key_file_lock():
        default_key_path = APP_DIR / "config" / "card-number.key"
        use_recovery_copy = KEY_PATH == default_key_path
        recovery_key = APP_DIR / "backups" / "keys" / "card-number.key"

        if KEY_PATH.is_file():
            data = KEY_PATH.read_bytes()

        elif use_recovery_copy and recovery_key.is_file():
            # Restore the live key from its private recovery copy.
            data = recovery_key.read_bytes()
            _write_private_key(KEY_PATH, data)

        else:
            data = secrets.token_bytes(32)
            _write_private_key(KEY_PATH, data)

        if len(data) != 32:
            raise CardEncryptionError(
                f"Card encryption key is invalid: {KEY_PATH}. "
                "Restore the matching key backup."
            )

        if use_recovery_copy:
            if recovery_key.exists():
                if recovery_key.read_bytes() != data:
                    raise CardEncryptionError(
                        "The private card-key recovery copy does not match "
                        "the active key. Stop before saving or decrypting "
                        "card numbers."
                    )
            else:
                _write_private_key(recovery_key, data)

        try:
            os.chmod(KEY_PATH, 0o600)
        except OSError:
            pass

        return data


def encrypt_card_number(value: str) -> str:
    if is_encrypted_card(value):
        return value

    digits = re.sub(r"[ -]", "", str(value))

    if not re.fullmatch(r"[0-9]{12,19}", digits):
        raise ValueError(
            "A complete 12-19 digit card number is required for encryption."
        )

    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_load_or_create_key()).encrypt(
        nonce,
        digits.encode("ascii"),
        _AAD,
    )
    payload = base64.urlsafe_b64encode(
        nonce + ciphertext
    ).decode("ascii").rstrip("=")

    return f"{TOKEN_PREFIX}{digits[-4:]}:{payload}"


def decrypt_card_number(value: str) -> str:
    if not is_encrypted_card(value):
        return value

    try:
        _prefix, last4, payload = value.split(":", 2)
        padded = payload + "=" * (-len(payload) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))

        if len(raw) < 12 + 16:
            raise ValueError("short ciphertext")

        plaintext = AESGCM(_load_or_create_key()).decrypt(
            raw[:12],
            raw[12:],
            _AAD,
        )
        digits = plaintext.decode("ascii")

        if (
            not re.fullmatch(r"[0-9]{12,19}", digits)
            or digits[-4:] != last4
        ):
            raise ValueError("invalid plaintext")

        return digits

    except Exception as exc:
        raise CardEncryptionError(
            "Unable to decrypt the stored card number. "
            "Check the card encryption key backup."
        ) from exc


def encrypt_profile_value(field_key: str, value: str) -> str:
    if not is_card_field_key(field_key) or not value or is_encrypted_card(value):
        return value

    # Preserve legacy masked values that cannot be recovered.
    if is_masked_card(value):
        return value

    return encrypt_card_number(value)


def mask_card_value(value: str) -> str:
    if is_encrypted_card(value):
        try:
            last4 = value.split(":", 2)[1]
            if re.fullmatch(r"[0-9]{4}", last4):
                return f"[encrypted card •••• {last4}]"
        except (IndexError, ValueError):
            pass

        return "[encrypted card number]"

    if re.fullmatch(r"[0-9]{12,19}", str(value)):
        return f"[card number •••• {str(value)[-4:]}]"

    return "[card number]"
