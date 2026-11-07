from pdfunlocker.profiles import card_crypto


def test_missing_active_key_is_restored_from_recovery_copy(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    key_path = app_dir / "config" / "card-number.key"

    monkeypatch.setattr(card_crypto, "APP_DIR", app_dir)
    monkeypatch.setattr(card_crypto, "KEY_PATH", key_path)

    encrypted = card_crypto.encrypt_card_number("4111111111111111")

    recovery_path = app_dir / "backups" / "keys" / "card-number.key"
    assert key_path.is_file()
    assert recovery_path.is_file()

    original_key = recovery_path.read_bytes()
    key_path.unlink()

    assert card_crypto.decrypt_card_number(encrypted) == "4111111111111111"
    assert key_path.read_bytes() == original_key


def test_mismatched_recovery_key_is_rejected(tmp_path, monkeypatch):
    app_dir = tmp_path / "app"
    key_path = app_dir / "config" / "card-number.key"

    monkeypatch.setattr(card_crypto, "APP_DIR", app_dir)
    monkeypatch.setattr(card_crypto, "KEY_PATH", key_path)

    encrypted = card_crypto.encrypt_card_number("4111111111111111")

    recovery_path = app_dir / "backups" / "keys" / "card-number.key"
    recovery_path.write_bytes(b"X" * 32)

    with pytest.raises(card_crypto.CardEncryptionError):
        card_crypto.decrypt_card_number(encrypted)


def test_invalid_active_key_length_is_rejected(tmp_path, monkeypatch):
    key_path = tmp_path / "keys" / "card-number.key"
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(b"invalid-key")

    monkeypatch.setattr(card_crypto, "KEY_PATH", key_path)

    with pytest.raises(card_crypto.CardEncryptionError):
        card_crypto.encrypt_card_number("4111111111111111")


def test_malformed_ciphertext_raises_card_encryption_error():
    with pytest.raises(card_crypto.CardEncryptionError):
        card_crypto.decrypt_card_number("ENCv1:1234:!")


def test_tampered_ciphertext_is_rejected(tmp_path, monkeypatch):
    key_path = tmp_path / "keys" / "card-number.key"
    monkeypatch.setattr(card_crypto, "KEY_PATH", key_path)

    encrypted = card_crypto.encrypt_card_number("4111111111111111")
    prefix, last4, payload = encrypted.split(":", 2)

    replacement = "A" if payload[0] != "A" else "B"
    tampered = f"{prefix}:{last4}:{replacement}{payload[1:]}"

    with pytest.raises(card_crypto.CardEncryptionError):
        card_crypto.decrypt_card_number(tampered)


import pytest
