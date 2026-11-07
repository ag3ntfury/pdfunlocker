from pdfunlocker.profiles.validation import validate_profile_values

def test_multiple_mobile_email_pincode_and_bank_values_validate_together():
    values = {
        "PROFILE_ID": "9001", "PROFILE_NAME": "Regression Fixture",
        "FIRST_NAME": "Rupesh", "LAST_NAME": "Bhadarka",
        "MOBILE_01": "+919876543210", "MOBILE_02": "+447911123456",
        "EMAIL_01": "one@example.com", "EMAIL_02": "two@example.org",
        "PINCODE_01": "361305", "PINCODE_02": "GB:SW1A 1AA",
        "PAN": "ABCDE1234F", "AADHAAR": "2345XXXX0124",
        "BANK_1200A_01": "State Bank of India",
        "BANK_1200B_01": "SBIN0001234",
        "BANK_1200C_01": "CIF123", "BANK_1200D_01": "CUST123",
        "BANK_1200E_01": "1234567890", "BANK_1200E_02": "9876543210",
        "GSTIN_01": "27AAPFU0939F1ZV", "GSTIN_02": "27AAPFU0939F1ZV",
        "TAN_01": "MUMA12345B", "TAN_02": "ABCD00001Z",
    }
    assert validate_profile_values(values) == []

def test_one_invalid_repeatable_value_reports_its_exact_field_key():
    errors = validate_profile_values({
        "MOBILE_01": "+919876543210",
        "MOBILE_02": "123",
        "EMAIL_01": "one@example.com",
        "EMAIL_02": "bad-email",
    })
    assert any(item.startswith("MOBILE_02:") for item in errors)
    assert any(item.startswith("EMAIL_02:") for item in errors)
    assert not any(item.startswith("MOBILE_01:") for item in errors)
    assert not any(item.startswith("EMAIL_01:") for item in errors)
