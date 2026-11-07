from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from pdfunlocker.profiles import card_crypto, store
from pdfunlocker.profiles import backup as profile_backup


PASSPHRASE = "correct horse battery staple 2026"
CARD = "4111111111111111"


def _make_db(path: Path, *, card_value: str | None = None, profile_name: str = "Original") -> None:
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.executescript(f"""
        PRAGMA foreign_keys=ON;
        CREATE TABLE profiles(profile_id INTEGER PRIMARY KEY, name TEXT NOT NULL, legacy_path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE field_definitions(field_number INTEGER PRIMARY KEY, field_id TEXT, field_key TEXT NOT NULL UNIQUE, label TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'Custom', allows_multiple INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, is_builtin INTEGER NOT NULL DEFAULT 0, is_custom INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE profile_banks(bank_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE, bank_sequence INTEGER NOT NULL, group_code INTEGER NOT NULL, bank_name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE profile_values(value_id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE, bank_id INTEGER REFERENCES profile_banks(bank_id) ON DELETE SET NULL, value_instance_id TEXT, field_key TEXT NOT NULL, value_sequence INTEGER NOT NULL DEFAULT 0, value TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE value_counters(profile_id INTEGER NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE, field_number INTEGER NOT NULL REFERENCES field_definitions(field_number), next_sequence INTEGER NOT NULL, PRIMARY KEY(profile_id, field_number));
        CREATE TABLE schema_metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_metadata VALUES('schema_version','4');
        INSERT INTO profiles VALUES(1,'{profile_name}','', 'now','now');
    """)
    if card_value is not None:
        db.execute("INSERT INTO profile_values(profile_id,field_key,value,value_sequence,created_at,updated_at) VALUES(1,'CARD_NO',?,0,'now','now')", (card_value,))
    db.commit()
    db.close()


def _token(key: bytes, digits: str = CARD) -> str:
    import base64
    import secrets
    nonce = secrets.token_bytes(12)
    encrypted = AESGCM(key).encrypt(nonce, digits.encode(), b"PDFUnlocker:card-number:v1")
    payload = base64.urlsafe_b64encode(nonce + encrypted).decode().rstrip("=")
    return f"ENCv1:{digits[-4:]}:{payload}"


@pytest.fixture

def backup_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app_dir = tmp_path / "app"
    key_path = app_dir / "config" / "card-number.key"
    recovery_path = app_dir / "backups" / "keys" / "card-number.key"
    monkeypatch.setattr(profile_backup, "APP_DIR", app_dir)
    monkeypatch.setattr(card_crypto, "KEY_PATH", key_path)
    db_path = tmp_path / "database" / "profiles.sqlite3"
    db_path.parent.mkdir()
    key = b"K" * 32
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(key)
    recovery_path.parent.mkdir(parents=True)
    recovery_path.write_bytes(key)
    _make_db(db_path, card_value=_token(key))
    monkeypatch.setattr(store, "DB_PATH", db_path)
    return db_path, key_path, recovery_path, key


def test_create_backup_encrypts_and_lists(backup_env, tmp_path: Path):
    db_path, key_path, recovery_path, key = backup_env
    out = profile_backup.create_backup(PASSPHRASE)
    assert out.exists() and out.stat().st_mode & 0o777 == 0o600
    payload = out.read_bytes()
    assert b"Original" not in payload
    assert CARD.encode() not in payload
    assert key not in payload
    assert profile_backup.list_backups()[0]["path"] == out


def test_wrong_passphrase_and_tampering_are_rejected(backup_env, tmp_path: Path):
    db_path, _key_path, _recovery_path, _key = backup_env
    out = profile_backup.create_backup(PASSPHRASE)
    with sqlite3.connect(db_path) as db:
        before = db.execute("SELECT name FROM profiles WHERE profile_id=1").fetchone()[0]
    with pytest.raises(profile_backup.ProfileBackupError, match="authentication"):
        profile_backup.restore_backup(out, "wrong passphrase value")
    with sqlite3.connect(db_path) as db:
        after = db.execute("SELECT name FROM profiles WHERE profile_id=1").fetchone()[0]
    assert after == before
    damaged = tmp_path / "damaged.pupb"
    raw = bytearray(out.read_bytes())
    raw[-25] ^= 0x40
    damaged.write_bytes(raw)
    with pytest.raises(profile_backup.ProfileBackupError):
        profile_backup.restore_backup(damaged, PASSPHRASE)


def test_restore_replaces_db_and_preserves_safety_backup(backup_env, tmp_path: Path):
    db_path, key_path, recovery_path, key = backup_env
    out = profile_backup.create_backup(PASSPHRASE)
    _make_db(db_path, profile_name="Changed")
    safety, manifest = profile_backup.restore_backup(out, PASSPHRASE)
    db = sqlite3.connect(db_path)
    try:
        assert db.execute("SELECT name FROM profiles WHERE profile_id=1").fetchone()[0] == "Original"
        token = db.execute("SELECT value FROM profile_values WHERE field_key='CARD_NO'").fetchone()[0]
    finally:
        db.close()
    assert card_crypto.decrypt_card_number(token) == CARD
    assert safety.exists()
    assert db_path.stat().st_mode & 0o777 == 0o600
    assert manifest["profile_count"] == 1
    assert key_path.read_bytes() == key
    assert recovery_path.read_bytes() == key


def test_refuses_to_overwrite_existing_backup(backup_env, tmp_path: Path):
    out = profile_backup.create_backup(PASSPHRASE)
    with pytest.raises(profile_backup.ProfileBackupError, match="overwrite"):
        profile_backup.create_backup(PASSPHRASE, out)


def test_bad_database_key_is_rejected_before_restore(backup_env, tmp_path: Path):
    db_path, key_path, recovery_path, key = backup_env
    out = profile_backup.create_backup(PASSPHRASE)
    # Corrupt the recovery copy. Backup and restore must not silently select one.
    recovery_path.write_bytes(b"X" * 32)
    with pytest.raises(profile_backup.ProfileBackupError, match="differ"):
        profile_backup.create_backup(PASSPHRASE, tmp_path / "should-not-exist.pupb")


def test_verify_backup_validates_without_changing_active_database_or_keys(backup_env, tmp_path: Path):
    db_path, key_path, recovery_path, key = backup_env
    out = profile_backup.create_backup(PASSPHRASE)
    before_db = db_path.read_bytes()
    before_key = key_path.read_bytes()
    before_recovery = recovery_path.read_bytes()

    result = profile_backup.verify_backup(out, PASSPHRASE)

    assert result["verified"] is True
    assert result["schema_version"] == "4"
    assert result["profile_count"] == 1
    assert result["value_count"] == 1
    assert result["encrypted_card_count"] == 1
    assert result["includes_card_key"] is True
    assert db_path.read_bytes() == before_db
    assert key_path.read_bytes() == before_key == key
    assert recovery_path.read_bytes() == before_recovery == key


def test_verify_backup_rejects_wrong_passphrase_without_live_changes(backup_env):
    db_path, key_path, recovery_path, _key = backup_env
    out = profile_backup.create_backup(PASSPHRASE)
    before_db = db_path.read_bytes()
    before_key = key_path.read_bytes()
    before_recovery = recovery_path.read_bytes()

    with pytest.raises(profile_backup.ProfileBackupError, match="authentication"):
        profile_backup.verify_backup(out, "definitely the wrong passphrase")

    assert db_path.read_bytes() == before_db
    assert key_path.read_bytes() == before_key
    assert recovery_path.read_bytes() == before_recovery


def test_verify_backup_rejects_tampered_file(backup_env, tmp_path: Path):
    out = profile_backup.create_backup(PASSPHRASE)
    damaged = tmp_path / "damaged-verify.pupb"
    raw = bytearray(out.read_bytes())
    raw[-25] ^= 0x20
    damaged.write_bytes(raw)
    with pytest.raises(profile_backup.ProfileBackupError):
        profile_backup.verify_backup(damaged, PASSPHRASE)



def test_manifest_reader_rejects_oversized_manifest(tmp_path: Path):
    import io
    import zipfile

    payload = io.BytesIO()
    oversized = b" " * (profile_backup._MAX_MANIFEST + 1)

    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("manifest.json", oversized)

    with zipfile.ZipFile(io.BytesIO(payload.getvalue()), "r") as archive:
        with pytest.raises(profile_backup.ProfileBackupError, match="manifest"):
            profile_backup._read_manifest(archive)

# Profile-store locking regression coverage.
def _hold_profile_lock_in_child(database_path, acquired, release):
    from pathlib import Path
    from pdfunlocker.profiles import store as child_store

    child_store.DB_PATH = Path(database_path)
    with child_store.profile_store_lock(child_store.DB_PATH):
        acquired.set()
        release.wait(10)


def test_profile_store_lock_is_reentrant(backup_env):
    db_path, *_ = backup_env
    with store.profile_store_lock(db_path):
        with store.profile_store_lock(db_path):
            with store._connect() as db:
                assert db.execute("SELECT 1").fetchone()[0] == 1

def test_profile_store_lock_excludes_another_process(backup_env):
    import multiprocessing
    import threading

    db_path, *_ = backup_env
    try:
        context = multiprocessing.get_context("fork")
    except ValueError:
        pytest.skip("This cross-process locking test requires fork support.")
    acquired = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_profile_lock_in_child,
        args=(str(db_path), acquired, release),
    )
    process.start()
    try:
        assert acquired.wait(3), "child process did not acquire profile lock"
        thread_acquired = threading.Event()

        def attempt_lock():
            with store.profile_store_lock(db_path):
                thread_acquired.set()

        thread = threading.Thread(target=attempt_lock, daemon=True)
        thread.start()
        assert not thread_acquired.wait(0.25), "lock was not exclusive across processes"
        release.set()
        assert thread_acquired.wait(3), "parent did not acquire lock after child released it"
        thread.join(3)
    finally:
        release.set()
        process.join(3)
        if process.is_alive():
            process.terminate()
            process.join(2)
    assert process.exitcode == 0

def test_create_backup_waits_for_profile_store_lock(backup_env, tmp_path: Path):
    import threading

    db_path, *_ = backup_env
    started = threading.Event()
    finished = threading.Event()
    errors = []

    def create():
        started.set()
        try:
            profile_backup.create_backup(PASSPHRASE, tmp_path / "locked.pupb")
        except Exception as exc:  # surfaced in the main test thread
            errors.append(exc)
        finally:
            finished.set()

    with store.profile_store_lock(db_path):
        thread = threading.Thread(target=create, daemon=True)
        thread.start()
        assert started.wait(2)
        assert not finished.wait(0.25), "backup bypassed the profile-store lock"
    assert finished.wait(5), "backup did not continue after lock release"
    thread.join(2)
    assert not errors, errors



# Additional stress and failure-path tests for profile database locking.
def test_restore_waits_for_profile_store_lock(backup_env, tmp_path: Path):
    import threading

    db_path, *_ = backup_env
    source_backup = profile_backup.create_backup(PASSPHRASE, tmp_path / "source.pupb")
    _make_db(db_path, profile_name="Changed-before-restore")
    started = threading.Event()
    finished = threading.Event()
    result = []
    errors = []

    def restore():
        started.set()
        try:
            result.append(profile_backup.restore_backup(source_backup, PASSPHRASE))
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    with store.profile_store_lock(db_path):
        thread = threading.Thread(target=restore, daemon=True)
        thread.start()
        assert started.wait(2), "restore worker did not start"
        assert not finished.wait(0.35), "restore bypassed the profile-store lock"
    assert finished.wait(10), "restore did not continue after lock release"
    thread.join(2)
    assert not thread.is_alive(), "restore worker did not terminate"
    assert not errors, errors
    with sqlite3.connect(db_path) as db:
        name = db.execute("SELECT name FROM profiles WHERE profile_id=1").fetchone()[0]
    assert name == "Original"
    assert result and result[0][0].is_file(), "restore safety backup was not created"


def test_parallel_backup_requests_all_complete(backup_env, tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor

    destinations = [tmp_path / f"parallel-{index}.pupb" for index in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(
            lambda path: profile_backup.create_backup(PASSPHRASE, path),
            destinations,
        ))
    assert set(outputs) == set(destinations)
    for path in outputs:
        assert path.is_file() and path.stat().st_size > 0
        assert profile_backup.verify_backup(path, PASSPHRASE)["verified"] is True


def test_concurrent_store_writes_are_not_lost(backup_env):
    from concurrent.futures import ThreadPoolExecutor

    db_path, *_ = backup_env
    workers = 6
    writes_per_worker = 12

    def write_batch(worker):
        with store._connect() as db:
            for index in range(writes_per_worker):
                db.execute(
                    "INSERT INTO profile_values(profile_id, field_key, value_sequence, value, created_at, updated_at) "
                    "VALUES(1, ?, ?, ?, 'now', 'now')",
                    (f"STRESS_{worker}", index, f"{worker}:{index}"),
                )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(write_batch, range(workers)))
    with sqlite3.connect(db_path) as db:
        count = db.execute(
            "SELECT COUNT(*) FROM profile_values WHERE field_key LIKE 'STRESS_%'"
        ).fetchone()[0]
    assert count == workers * writes_per_worker


def test_profile_lock_is_released_after_exception(backup_env):
    import threading

    db_path, *_ = backup_env
    with pytest.raises(RuntimeError, match="injected failure"):
        with store.profile_store_lock(db_path):
            raise RuntimeError("injected failure")

    acquired = threading.Event()
    errors = []

    def acquire_from_another_thread():
        try:
            with store.profile_store_lock(db_path):
                acquired.set()
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=acquire_from_another_thread, daemon=True)
    thread.start()
    assert acquired.wait(3), "profile lock remained held after exception"
    thread.join(2)
    assert not thread.is_alive()
    assert not errors, errors


def test_profile_lock_is_released_when_process_is_terminated(backup_env):
    import multiprocessing
    import threading

    db_path, *_ = backup_env
    try:
        context = multiprocessing.get_context("fork")
    except ValueError:
        pytest.skip("This process-termination test requires fork support.")
    acquired_in_child = context.Event()
    never_release = context.Event()
    process = context.Process(
        target=_hold_profile_lock_in_child,
        args=(str(db_path), acquired_in_child, never_release),
    )
    process.start()
    try:
        assert acquired_in_child.wait(3), "child process did not acquire profile lock"
        process.terminate()
        process.join(3)
        assert not process.is_alive(), "child process did not terminate"
        acquired_in_parent = threading.Event()
        errors = []

        def acquire_after_child_death():
            try:
                with store.profile_store_lock(db_path):
                    acquired_in_parent.set()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=acquire_after_child_death, daemon=True)
        thread.start()
        assert acquired_in_parent.wait(3), "OS lock was not released after process termination"
        thread.join(2)
        assert not thread.is_alive()
        assert not errors, errors
    finally:
        if process.is_alive():
            process.kill()
            process.join(2)


def test_restore_rolls_back_database_and_both_keys_after_replacement_failure(
    backup_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path, active_key_path, recovery_key_path, original_key = backup_env
    source_backup = profile_backup.create_backup(PASSPHRASE, tmp_path / "rollback-source.pupb")
    _make_db(db_path, profile_name="Must-survive-failed-restore")
    original_active_key = active_key_path.read_bytes()
    original_recovery_key = recovery_key_path.read_bytes()
    real_replace = profile_backup._replace_file_atomically
    calls = {"count": 0}

    def fail_once_on_recovery_key(target, data):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected recovery-key replacement failure")
        return real_replace(target, data)

    monkeypatch.setattr(profile_backup, "_replace_file_atomically", fail_once_on_recovery_key)
    with pytest.raises(profile_backup.ProfileBackupError, match="original files were restored"):
        profile_backup.restore_backup(source_backup, PASSPHRASE)

    with sqlite3.connect(db_path) as db:
        name = db.execute("SELECT name FROM profiles WHERE profile_id=1").fetchone()[0]
    assert name == "Must-survive-failed-restore"
    assert active_key_path.read_bytes() == original_active_key == original_key
    assert recovery_key_path.read_bytes() == original_recovery_key == original_key
    assert calls["count"] >= 4, "rollback did not attempt to restore both key files"
