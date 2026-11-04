import re

from pdfunlocker.profiles import card_crypto


def test_card_encrypt_decrypt_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(card_crypto, "KEY_PATH", tmp_path / "keys" / "card.key")
    original = "4111111111111111"
    encrypted = card_crypto.encrypt_card_number(original)
    assert card_crypto.is_encrypted_card(encrypted)
    assert original not in encrypted
    assert card_crypto.decrypt_card_number(encrypted) == original
    assert card_crypto.mask_card_value(encrypted).endswith("1111]")


def test_encrypt_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(card_crypto, "KEY_PATH", tmp_path / "keys" / "card.key")
    encrypted = card_crypto.encrypt_card_number("4111111111111111")
    assert card_crypto.encrypt_card_number(encrypted) == encrypted


def test_card_field_keys():
    assert card_crypto.is_card_field_key("BANK_1200F_01")
    assert card_crypto.is_card_field_key("CREDIT_CARD_NUMBER_02")
    assert not card_crypto.is_card_field_key("BANK_1200E_01")


def test_rule_field_resolver_decrypts_card_only_for_matching_rule(monkeypatch, tmp_path):
    from pdfunlocker.profiles import store
    from pdfunlocker.pdf.candidates import _resolve_field_part
    from pdfunlocker.rules.manager import FieldPart

    old_db = store.DB_PATH
    old_key = card_crypto.KEY_PATH
    store.DB_PATH = tmp_path / "profiles.sqlite3"
    card_crypto.KEY_PATH = tmp_path / "keys" / "card-number.key"
    try:
        store.initialize()
        store.ensure_bank_group(1200)
        store.save_profile(
            tmp_path / "profile.env",
            {
                "PROFILE_ID": "55", "PROFILE_NAME": "Rule Test",
                "BANK_1200A": "Example Bank",
                "BANK_1200F_01": "4111111111111111",
            },
        )
        profile = store.load_profile(55)
        encrypted = profile["BANK_1200F_01"]
        assert card_crypto.is_encrypted_card(encrypted)
        assert _resolve_field_part(FieldPart(field_id="1200F"), profile) == ["4111111111111111"]
        assert profile["BANK_1200F_01"] == encrypted
    finally:
        store.DB_PATH = old_db
        card_crypto.KEY_PATH = old_key
