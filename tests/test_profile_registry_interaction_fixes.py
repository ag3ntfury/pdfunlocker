from pdfunlocker.profiles import manager, validation


def test_retry_prompt_accepts_corrected_value_directly(monkeypatch):
    answers = iter(["US:90210"])
    prompts = []
    def ask(prompt):
        prompts.append(prompt)
        return next(answers)
    result = manager._validate_with_correction("PINCODE_01", "000000", ask)
    assert result == "US:90210"
    assert prompts == ["Invalid value. Press Enter to skip or insert a corrected value: "]


def test_retry_prompt_empty_skips():
    result = manager._validate_with_correction("UAN_01", "123", lambda prompt: "")
    assert result is None


def test_indian_pincode_default_and_international_explicit():
    assert validation.validate_field_value("PINCODE_01", "361305") == ("361305", None)
    assert validation.validate_field_value("PINCODE_01", "000000")[0] is None
    assert validation.validate_field_value("PINCODE_01", "US:90210") == ("US:90210", None)
    assert validation.validate_field_value("PINCODE_01", "90210")[0] is None


def test_acronym_labels():
    assert manager.display_label("UAN") == "UAN"
    assert manager.display_label("PRAN") == "PRAN"
    assert manager.display_label("PPO_NUMBER") == "PPO Number"
    assert manager.display_label("GSTIN") == "GSTIN"
    assert manager.display_label("TAN") == "TAN"
    assert manager.display_label("EMPLOYEE_ID") == "Employee ID"


def test_profile_collection_calls_are_in_permanent_id_order(monkeypatch):
    calls = []
    monkeypatch.setattr(manager, "collect_fixed_fields", lambda values, modifying, input_func, field_keys=None: calls.append(("fixed", field_keys)))
    monkeypatch.setattr(manager, "collect_repeatable_fields", lambda values, modifying, input_func, prefixes=None: calls.append(("repeatable", prefixes)))
    monkeypatch.setattr(manager, "collect_bank_fields", lambda values, modifying, input_func: calls.append(("bank", None)))
    manager.collect_profile_values({"PROFILE_ID": "1"})
    assert calls == [
        ("fixed", {"TITLE", "FIRST_NAME", "LAST_NAME", "MIDDLE_NAME", "MOTHER_NAME", "DOB"}),
        ("repeatable", {"MOBILE", "EMAIL", "PINCODE"}),
        ("fixed", {"PAN", "AADHAAR"}),
        ("bank", None),
        ("fixed", {"INCORPORATION_DATE"}),
        ("repeatable", {"TAN", "GSTIN", "BUSINESS_NAME", "BUSINESS_REGISTRATION_NUMBER"}),
        ("repeatable", {"EMPLOYEE_ID", "UAN", "PPO_NUMBER", "PRAN"}),
        ("repeatable", {"POLICY_NUMBER", "INSURER_NAME", "POLICY_TYPE"}),
        ("repeatable", {"ROLL_NUMBER", "INSTITUTION_NAME", "QUALIFICATION", "COURSE", "ENROLLMENT_NUMBER", "REGISTRATION_NUMBER"}),
    ]


def test_bank_field_display_labels_keep_acronyms():
    assert manager.display_label("BANK_1200A") == "Bank Name"
    assert manager.display_label("BANK_1200B") == "IFSC"
    assert manager.display_label("BANK_1200C") == "CIF"
    assert manager.display_label("BANK_1200F") == "Card Number"
