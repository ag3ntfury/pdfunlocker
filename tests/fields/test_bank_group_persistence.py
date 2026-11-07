from pdfunlocker.profiles import store


def test_bank_group_definitions_share_type_ids_and_have_correct_multiplicity(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    first = store.ensure_bank_group(1200)
    second = store.ensure_bank_group(1201)
    expected = ["4169", "4223", "4298", "4356", "4424", "4487"]
    assert [item["field_id"] for item in first] == expected
    assert [item["field_id"] for item in second] == expected
    assert [item["allows_multiple"] for item in first] == [True, True, True, True, True, True]


def test_multiple_bank_groups_allocate_sequentially_without_reusing_definitions(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    assert store.next_bank_group() == 1201
    store.ensure_bank_group(1201)
    assert store.next_bank_group() == 1202
    store.ensure_bank_group(1202)
    assert store.next_bank_group() == 1203


def test_bank_group_range_is_enforced_at_storage_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    import pytest
    with pytest.raises(ValueError):
        store.ensure_bank_group(1199)
    with pytest.raises(ValueError):
        store.ensure_bank_group(1700)
