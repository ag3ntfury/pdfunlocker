import re

from pdfunlocker.profiles import manager, store


def test_bank_prompt_order_and_add_another_bank_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    answers = iter([
        "SBI", "SBIN0001234", "CIF123", "CUST123",
        "1234567890", "", "4111111111111111", "",
        "",  # Add another bank? Enter skips.
    ])
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return next(answers)

    values = {"PROFILE_ID": "1", "PROFILE_NAME": "Test"}
    manager.collect_bank_fields(values, input_func=ask)

    assert values["BANK_1200A_01"] == "SBI"
    assert values["BANK_1200B_01"] == "SBIN0001234"
    assert values["BANK_1200C_01"] == "CIF123"
    assert values["BANK_1200D_01"] == "CUST123"
    assert values["BANK_1200E_01"] == "1234567890"
    assert values["BANK_1200F_01"] == "4111111111111111"
    labels = [prompt.split(" [", 1)[0].rstrip(": ") for prompt in prompts]
    assert labels[:8] == [
        "Bank Name", "IFSC", "CIF", "Customer ID",
        "Account Number", "Account Number",
        "Card Number (full 12-19 digits; encrypted)",
        "Card Number (full 12-19 digits; encrypted)",
    ]
    assert prompts[-1] == "Add another bank? Y for yes; Enter to skip: "
    store.save_profile(tmp_path / "prompt-profile.env", values)
    with store._connect() as db:
        ids = db.execute(
            "SELECT field_key,value_instance_id FROM profile_values WHERE profile_id=1 ORDER BY field_key"
        ).fetchall()
    assert {row[0]: row[1] for row in ids}["BANK_1200A_01"] == "4169A"
    assert {row[0]: row[1] for row in ids}["BANK_1200B_01"] == "4223A"
    assert {row[0]: row[1] for row in ids}["BANK_1200E_01"] == "4424A"
    assert {row[0]: row[1] for row in ids}["BANK_1200F_01"] == "4487A"
    assert not any(re.search(r"\b[1-9][0-9]{3,4}[A-Z]*\b", prompt) for prompt in prompts)


def test_account_value_sequence_continues_between_banks_and_restarts_per_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    store.ensure_bank_group(1201)
    first_profile = {
        "PROFILE_ID": "1", "PROFILE_NAME": "One",
        "BANK_1200A_01": "SBI", "BANK_1200E_01": "111122223333",
        "BANK_1200E_02": "222233334444", "BANK_1201A_02": "HDFC",
        "BANK_1201E_03": "333344445555",
    }
    store.save_profile(tmp_path / "one.env", first_profile)
    assert store.next_value_sequence(1, "BANK_1201E", first_profile) == 4

    second_profile = {
        "PROFILE_ID": "2", "PROFILE_NAME": "Two",
        "BANK_1200A_01": "ICICI", "BANK_1200E_01": "333344445555",
    }
    store.save_profile(tmp_path / "two.env", second_profile)
    assert store.next_value_sequence(2, "BANK_1200E", second_profile) == 2

    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM profile_banks WHERE profile_id=1").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM profile_banks WHERE profile_id=2").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM profile_values WHERE bank_id IS NULL AND field_key LIKE 'BANK_%'").fetchone()[0] == 0
        account_ids = db.execute(
            "SELECT value_instance_id FROM profile_values WHERE profile_id=1 AND field_key LIKE 'BANK_%E_%' ORDER BY value_sequence"
        ).fetchall()
        assert [row[0] for row in account_ids] == ["4424A", "4424B", "4424C"]
        bank_name_ids = db.execute(
            "SELECT value_instance_id FROM profile_values WHERE profile_id=1 AND field_key LIKE 'BANK_%A_%' ORDER BY value_sequence"
        ).fetchall()
        assert [row[0] for row in bank_name_ids] == ["4169A", "4169B"]
        profile_two_account_ids = db.execute(
            "SELECT value_instance_id FROM profile_values WHERE profile_id=2 AND field_key LIKE 'BANK_%E_%'"
        ).fetchall()
        assert [row[0] for row in profile_two_account_ids] == ["4424A"]


def test_deleted_bank_value_suffix_is_never_compacted_or_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    original = {
        "PROFILE_ID": "30", "PROFILE_NAME": "No Reuse",
        "BANK_1200A_01": "SBI", "BANK_1200E_01": "111122223333",
        "BANK_1200E_02": "222233334444", "BANK_1201A_02": "HDFC",
        "BANK_1201E_03": "333344445555",
    }
    store.save_profile(tmp_path / "no-reuse.env", original)
    without_middle = {
        "PROFILE_ID": "30", "PROFILE_NAME": "No Reuse",
        "BANK_1200A_01": "SBI", "BANK_1200E_01": "111122223333",
        "BANK_1201A_02": "HDFC", "BANK_1201E_03": "333344445555",
    }
    store.save_profile(tmp_path / "no-reuse.env", without_middle)
    assert store.next_value_sequence(30, "BANK_1201E", without_middle) == 4
    with store._connect() as db:
        rows = db.execute(
            "SELECT field_key,value_instance_id FROM profile_values WHERE profile_id=30 AND field_key LIKE 'BANK_%E_%' ORDER BY value_sequence"
        ).fetchall()
    assert [(row[0], row[1]) for row in rows] == [
        ("BANK_1200E_01", "4424A"),
        ("BANK_1201E_03", "4424C"),
    ]
    with_new_value = dict(without_middle)
    with_new_value["BANK_1201E_04"] = "444455556666"
    store.save_profile(tmp_path / "no-reuse.env", with_new_value)
    with store._connect() as db:
        new_id = db.execute(
            "SELECT value_instance_id FROM profile_values WHERE profile_id=30 AND field_key='BANK_1201E_04'"
        ).fetchone()[0]
    assert new_id == "4424D"


def test_custom_field_prompt_requires_one_of_seven_categories(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    answers = iter(["Travel Tag", "TRAVEL_TAG", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    manager.add_profile_field()
    output = capsys.readouterr().out
    assert "A category is required" in output
    assert not any(item["field_key"] == "TRAVEL_TAG" for item in store.list_fields(include_archived=True))
