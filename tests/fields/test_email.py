import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize("value", ["one@example.com", "Rupesh.Bhadarka+test@example.co.in", "user_name@example.org", "User@例え.テスト", "a@b.co"])
def test_email_accepts_valid_syntax_and_preserves_original(value):
    assert validate_field_value("EMAIL", value) == (value, None)

@pytest.mark.parametrize(("field", "value"), [("EMAIL", "bad"), ("EMAIL_01", "a@@example.com"), ("EMAIL_02", "@example.com"), ("EMAIL_03", "a@"), ("EMAIL_04", "a@example"), ("EMAIL_05", "a..b@example.com"), ("EMAIL_06", "a b@example.com"), ("EMAIL_07", "a@example..com"), ("EMAIL_08", "a@-example.com"), ("EMAIL_09", "a@example.c"), ("EMAIL_10", " a@example.com"), ("EMAIL_11", "a@example.com "), ("EMAIL_12", "a\n@example.com")])
def test_email_rejects_malformed_addresses(field, value):
    normalized, error = validate_field_value(field, value)
    assert normalized is None and error

def test_email_multiple_slots_are_independent():
    for field, value in [("EMAIL_01", "one@example.com"), ("EMAIL_02", "two@example.org"), ("EMAIL_10", "three@example.net")]:
        assert validate_field_value(field, value) == (value, None)
