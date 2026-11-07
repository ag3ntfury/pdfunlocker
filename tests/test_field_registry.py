from pdfunlocker.profiles import store
from pdfunlocker.profiles.registry import FIELD_ID_BY_KEY, bank_field_id, bank_field_key, normalize_field_id


def test_permanent_non_bank_field_ids_are_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    fields = {item["field_key"]: item for item in store.list_fields(include_archived=True)}
    for key in ("TITLE", "FIRST_NAME", "MIDDLE_NAME", "LAST_NAME", "MOTHER_NAME", "DOB", "MOBILE", "EMAIL", "PINCODE", "PAN", "AADHAAR", "INCORPORATION_DATE", "TAN", "GSTIN", "EMPLOYEE_ID", "UAN", "PPO_NUMBER", "PRAN", "POLICY_NUMBER", "ROLL_NUMBER"):
        assert fields[key]["field_id"] == FIELD_ID_BY_KEY[key]


def test_bank_group_ids_are_shared_across_banks(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    first = store.ensure_bank_group(1200)
    second = store.ensure_bank_group(1201)
    assert [item["field_id"] for item in first] == ["4169", "4223", "4298", "4356", "4424", "4487"]
    assert [item["field_id"] for item in second] == ["4169", "4223", "4298", "4356", "4424", "4487"]
    assert bank_field_key(1202, "E") == "BANK_1202E"
    assert bank_field_id(1202, "F") == "4487"


def test_bank_multiplicity_is_correct(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    store.ensure_bank_group(1200)
    fields = {item["field_key"]: item for item in store.list_fields()}
    assert fields["BANK_1200A"]["allows_multiple"] == 1
    for suffix in "BCDEF":
        assert fields[f"BANK_1200{suffix}"]["allows_multiple"] == 1


def test_field_id_normalization_accepts_registered_builtins_and_legacy_ids():
    assert normalize_field_id("1248") == "1248"
    assert normalize_field_id("1200e") == "4424"
    assert normalize_field_id("001") == "1248"
    assert normalize_field_id("1700") == "6137"
    assert normalize_field_id("2500") is None
    assert normalize_field_id("9999") is None
    assert normalize_field_id("9999Z") is None
    assert normalize_field_id("4169A") is None
    assert normalize_field_id("4169ZZ") is None
    assert normalize_field_id("4424B", allow_value_instance=True) == "4424"


def test_custom_numeric_field_id_requires_database_registry_membership():
    assert normalize_field_id("6500") is None
    assert normalize_field_id("6500", known_ids={"6500"}) == "6500"
    assert normalize_field_id("6500", known_ids={"6501"}) is None
    assert normalize_field_id("4169", known_ids={"6500"}) is None
    assert normalize_field_id("CUSTOM0001") is None
    assert normalize_field_id("CUSTOM0001", known_ids={"CUSTOM0001"}) == "CUSTOM0001"


def test_custom_fields_get_random_permanent_ids_inside_selected_group(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    number, key = store.add_field("Company Alias", "COMPANY_ALIAS", True, "Business")
    item = next(row for row in store.list_fields(include_archived=True) if row["field_key"] == key)
    field_id = int(item["field_id"])
    assert 6001 <= field_id <= 7000
    saved_id = item["field_id"]
    store.initialize()
    item = next(row for row in store.list_fields(include_archived=True) if row["field_key"] == key)
    assert item["field_id"] == saved_id
    assert normalize_field_id(saved_id) is None
    assert normalize_field_id(saved_id, known_ids={saved_id}) == saved_id
