from pdfunlocker.profiles import manager, store


def test_optional_empty_value_is_skipped():
    assert manager.normalize_and_validate("FIRST_NAME", "") == ""


def test_mobile_defaults_to_india():
    assert manager.normalize_and_validate("MOBILE_01", "9876543210") == "+919876543210"


def test_mobile_preserves_explicit_international_prefix():
    assert manager.normalize_and_validate("MOBILE_01", "+929876543210") == "+929876543210"
    assert manager.normalize_and_validate("MOBILE_02", "+447911123456") == "+447911123456"


def test_mobile_accepts_common_separators():
    assert manager.normalize_and_validate("MOBILE_01", "+91 (98765) 432-10") == "+919876543210"


def test_mobile_rejects_invalid_number():
    assert manager.normalize_and_validate("MOBILE_01", "123") is None


def test_email_is_validated_and_normalized():
    assert manager.normalize_and_validate("EMAIL_01", "User@Example.COM") == "user@example.com"
    assert manager.normalize_and_validate("EMAIL_01", "bad-email") is None


def test_email_accepts_internationalized_domain():
    assert manager.normalize_and_validate("EMAIL_01", "user@例え.テスト") == "user@例え.テスト"


def test_pan_format():
    assert manager.normalize_and_validate("PAN", "abcde1234f") == "ABCDE1234F"
    assert manager.normalize_and_validate("PAN", "ABCDE12345") is None


def test_international_postal_codes():
    assert manager.normalize_and_validate("PINCODE", "361305") == "361305"
    assert manager.normalize_and_validate("PINCODE", "SW1A 1AA") == "SW1A 1AA"
    assert manager.normalize_and_validate("PINCODE", "90210") == "90210"


def test_credit_card_luhn_validation():
    assert manager.normalize_and_validate("CREDIT_CARD_NUMBER_01", "4111 1111 1111 1111") == "4111111111111111"
    assert manager.normalize_and_validate("CREDIT_CARD_NUMBER_01", "4111111111111112") is None


def test_international_account_number():
    assert manager.normalize_and_validate("ACCOUNT_NUMBER_01", "GB29 NWBK 6016 1331") == "GB29NWBK60161331"
    assert manager.normalize_and_validate("ACCOUNT_NUMBER_01", "123") is None


def test_title_choices():
    assert manager.normalize_and_validate("TITLE", "mr") == "Mr"
    assert manager.normalize_and_validate("TITLE", "Dr") == "Dr"
    assert manager.normalize_and_validate("TITLE", "invalid") is None


def test_unicode_person_name():
    assert manager.normalize_and_validate("FIRST_NAME", "José O’Connor-Smith") == "JOSÉ O’CONNOR-SMITH"
    assert manager.normalize_and_validate("FIRST_NAME", "John123") is None


def test_title_gets_permanent_global_field_id(tmp_path, monkeypatch):
    old_path = store.DB_PATH
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    try:
        store.initialize()
        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        title_id = fields["TITLE"]["field_number"]
        assert title_id > 30
        assert fields["TITLE"]["is_builtin"] == 1

        first_id, _ = store.add_field("Travel Tag", "TRAVEL_TAG", False)
        assert first_id > title_id

        store.archive_field("TRAVEL_TAG")
        next_id, _ = store.add_field("Family Code", "FAMILY_CODE", False)
        assert next_id > first_id

        fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
        assert fields["TITLE"]["field_number"] == title_id
        assert fields["TRAVEL_TAG"]["field_number"] == first_id
    finally:
        monkeypatch.setattr(store, "DB_PATH", old_path)


def test_builtin_repeatable_suffix_is_not_reused_after_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()

    profile_path = tmp_path / "profile.env"
    original = {
        "PROFILE_ID": "101",
        "PROFILE_NAME": "Suffix Test",
        "MOBILE_01": "+919876543210",
    }
    store.save_profile(profile_path, original)

    # Simulate deleting the existing value and saving the profile.
    updated = {
        "PROFILE_ID": "101",
        "PROFILE_NAME": "Suffix Test",
    }
    store.save_profile(profile_path, updated)

    assert store.next_value_sequence(101, "MOBILE", updated) == 2


def test_custom_repeatable_suffix_is_not_reused_after_deletion(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()

    field_id, field_key = store.add_field(
        "Travel Contact",
        "TRAVEL_CONTACT",
        allows_multiple=True,
    )
    assert field_id > 31

    profile_path = tmp_path / "profile.env"
    original = {
        "PROFILE_ID": "102",
        "PROFILE_NAME": "Custom Suffix Test",
        f"{field_key}_01": "First contact",
    }
    store.save_profile(profile_path, original)

    # Remove the value but retain its sequence counter.
    updated = {
        "PROFILE_ID": "102",
        "PROFILE_NAME": "Custom Suffix Test",
    }
    store.save_profile(profile_path, updated)

    assert store.next_value_sequence(102, field_key, updated) == 2
