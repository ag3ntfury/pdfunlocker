import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("CUSTOMER_ID", "ABC12345", "ABC12345"), ("CUSTOMER_ID_01", "cust. 123", "CUST.123"), ("BANK_1200D_01", "cust/2026-01", "CUST/2026-01"), ("BANK_1201D_02", "A-123", "A-123")])
def test_customer_id_valid_values(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["!ABC", "_ABC", "ABC_123", "A" * 129])
def test_customer_id_rejects_invalid_values(value):
    normalized, error = validate_field_value("CUSTOMER_ID_01", value)
    assert normalized is None and error
