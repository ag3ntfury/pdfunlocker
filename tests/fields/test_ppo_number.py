import pytest
from pdfunlocker.profiles.validation import validate_field_value

@pytest.mark.parametrize(("field", "value", "expected"), [("PPO_NUMBER", "PPO/12345/2026", "PPO/12345/2026"), ("PPO_NUMBER_01", "ppo 123", "PPO123"), ("PPO_NUMBER_02", "AB-123.45", "AB-123.45")])
def test_ppo_number_valid_values(field, value, expected):
    assert validate_field_value(field, value) == (expected, None)

@pytest.mark.parametrize("value", ["_PPO123", ".PPO123", "PPO_123", "PPO@123", "A" * 129])
def test_ppo_number_rejects_invalid_values(value):
    normalized, error = validate_field_value("PPO_NUMBER", value)
    assert normalized is None and error
