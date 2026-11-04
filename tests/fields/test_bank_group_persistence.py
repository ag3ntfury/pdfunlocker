from pdfunlocker.profiles import store


def test_bank_group_definitions_mark_name_single_and_details_repeatable(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "profiles.sqlite3")
    store.initialize()
    created = store.ensure_bank_group(1200)
    assert len(created) == 6
    assert [item["field_id"] for item in created] == ["1200A", "1200B", "1200C", "1200D", "1200E", "1200F"]
    assert [item["allows_multiple"] for item in created] == [False, True, True, True, True, True]


def test_multiple_bank_groups_allocate_sequentially_without_reusing_ids(tmp_path, monkeypatch):
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
