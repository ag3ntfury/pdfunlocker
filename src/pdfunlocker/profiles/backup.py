"""Encrypted, independently restorable backups for the profile SQLite store.

Format v1 uses Scrypt + chunked AES-256-GCM. Every chunk is authenticated,
including an explicit authenticated end marker so truncation is detected.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import struct
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from pdfunlocker.paths import APP_DIR
from pdfunlocker.profiles import card_crypto

MAGIC = b"PDFUNLOCKER-PROFILE-BACKUP\x00"
FORMAT_VERSION = 1
CHUNK_SIZE = 1024 * 1024
_SCRYPT_N = 1 << 15
_SCRYPT_R = 8
_SCRYPT_P = 1
_MAX_HEADER = 16 * 1024
_MAX_ARCHIVE = 2 * 1024 * 1024 * 1024
_MAX_MANIFEST = 64 * 1024
_REQUIRED_TABLES = {
    "profiles", "field_definitions", "profile_banks", "profile_values",
    "value_counters", "schema_metadata",
}


class ProfileBackupError(RuntimeError):
    """A profile backup could not be created, verified, or restored safely."""


def default_backup_dir() -> Path:
    return APP_DIR / "backups" / "profiles"


def _derive_key(passphrase: str, salt: bytes, *, n: int = _SCRYPT_N,
                r: int = _SCRYPT_R, p: int = _SCRYPT_P) -> bytes:
    if not isinstance(passphrase, str) or len(passphrase) < 12:
        raise ProfileBackupError("Passphrase must contain at least 12 characters.")
    try:
        return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode("utf-8"))
    except Exception as exc:
        raise ProfileBackupError("Could not derive the backup encryption key.") from exc


def _write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(name)
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)


def _private_temp(directory: Path, prefix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=prefix, dir=directory)
    os.close(fd)
    path = Path(name)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _snapshot_database(source_path: Path, target_path: Path, card_key: bytes | None) -> None:
    if not source_path.is_file():
        raise ProfileBackupError(f"Profile database does not exist: {source_path}")
    try:
        source = sqlite3.connect(f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True, timeout=30)
        target = sqlite3.connect(target_path)
        try:
            source.backup(target, pages=256, sleep=0.05)
            target.commit()
        finally:
            target.close()
            source.close()
    except sqlite3.Error as exc:
        raise ProfileBackupError(f"Could not snapshot the profile database: {exc}") from exc
    _validate_database(target_path, card_key)


def _validate_database(path: Path, card_key: bytes | None) -> dict:
    try:
        db = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise ProfileBackupError(f"Profile database integrity check failed: {integrity}")
            fk_errors = db.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise ProfileBackupError("Profile database contains foreign-key violations.")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            missing = sorted(_REQUIRED_TABLES - tables)
            if missing:
                raise ProfileBackupError("Not a supported profile database; missing tables: " + ", ".join(missing))
            meta = {str(row[0]): str(row[1]) for row in db.execute("SELECT key,value FROM schema_metadata")}
            schema_version = meta.get("schema_version")
            if schema_version != "4":
                raise ProfileBackupError(f"Unsupported profile schema version: {schema_version or 'unknown'} (expected 4). Run the application normally before backing up.")
            profiles = int(db.execute("SELECT COUNT(*) FROM profiles").fetchone()[0])
            values = db.execute("SELECT field_key,value FROM profile_values").fetchall()
            encrypted = 0
            for row in values:
                value = str(row["value"])
                if value.startswith(card_crypto.TOKEN_PREFIX):
                    encrypted += 1
                    if card_key is not None:
                        _decrypt_card_token(value, card_key)
            if encrypted and card_key is None:
                raise ProfileBackupError("Encrypted card values exist, but the matching card-encryption key is missing.")
            return {"schema_version": schema_version, "profile_count": profiles,
                    "value_count": len(values), "encrypted_card_count": encrypted}
        finally:
            db.close()
    except sqlite3.Error as exc:
        raise ProfileBackupError(f"Could not validate profile database: {exc}") from exc


def _decrypt_card_token(value: str, key: bytes) -> str:
    import base64
    try:
        _prefix, last4, payload = value.split(":", 2)
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        if len(raw) < 28 or len(key) != 32:
            raise ValueError("invalid token or key size")
        digits = AESGCM(key).decrypt(raw[:12], raw[12:], b"PDFUnlocker:card-number:v1").decode("ascii")
        if not (12 <= len(digits) <= 19 and digits.isdigit() and digits[-4:] == last4):
            raise ValueError("invalid card payload")
        return digits
    except Exception as exc:
        raise ProfileBackupError("The backup card-encryption key does not authenticate every stored card value.") from exc


def _read_matching_card_key() -> bytes | None:
    active = Path(card_crypto.KEY_PATH)
    recovery = APP_DIR / "backups" / "keys" / "card-number.key"
    active_data = active.read_bytes() if active.is_file() else None
    recovery_data = recovery.read_bytes() if recovery.is_file() else None
    if active_data is not None and len(active_data) != 32:
        raise ProfileBackupError("The active card-encryption key has an invalid length.")
    if recovery_data is not None and len(recovery_data) != 32:
        raise ProfileBackupError("The card-key recovery copy has an invalid length.")
    if active_data is not None and recovery_data is not None and active_data != recovery_data:
        raise ProfileBackupError("Active and recovery card-encryption keys differ. Resolve the key mismatch before backing up.")
    return active_data if active_data is not None else recovery_data


def _encrypt_stream(source: BinaryIO, destination: BinaryIO, passphrase: str) -> None:
    salt = secrets.token_bytes(16)
    nonce_prefix = secrets.token_bytes(8)
    header = {"version": FORMAT_VERSION, "kdf": "scrypt", "n": _SCRYPT_N,
              "r": _SCRYPT_R, "p": _SCRYPT_P, "salt": salt.hex(),
              "nonce_prefix": nonce_prefix.hex(), "chunk_size": CHUNK_SIZE,
              "cipher": "AES-256-GCM"}
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = _derive_key(passphrase, salt)
    aes = AESGCM(key)
    destination.write(MAGIC)
    destination.write(struct.pack(">I", len(header_bytes)))
    destination.write(header_bytes)
    index = 0
    while True:
        chunk = source.read(CHUNK_SIZE)
        if not chunk:
            break
        nonce = nonce_prefix + struct.pack(">I", index)
        encrypted = aes.encrypt(nonce, chunk, header_bytes + b"DATA" + struct.pack(">I", index))
        destination.write(struct.pack(">I", len(encrypted)))
        destination.write(encrypted)
        index += 1
        if index >= 0xFFFFFFFF:
            raise ProfileBackupError("Backup is too large for the supported format.")
    nonce = nonce_prefix + struct.pack(">I", index)
    final = aes.encrypt(nonce, b"", header_bytes + b"FINAL" + struct.pack(">I", index))
    destination.write(struct.pack(">I", len(final)))
    destination.write(final)


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise ProfileBackupError("Backup is truncated or malformed.")
    return data


def _decrypt_stream(source: BinaryIO, destination: BinaryIO, passphrase: str) -> None:
    if _read_exact(source, len(MAGIC)) != MAGIC:
        raise ProfileBackupError("This is not a PDF Unlocker profile backup.")
    header_len = struct.unpack(">I", _read_exact(source, 4))[0]
    if not 1 <= header_len <= _MAX_HEADER:
        raise ProfileBackupError("Invalid backup header length.")
    header_bytes = _read_exact(source, header_len)
    try:
        header = json.loads(header_bytes)
        if (header.get("version") != FORMAT_VERSION or header.get("kdf") != "scrypt"
                or header.get("cipher") != "AES-256-GCM" or header.get("chunk_size") != CHUNK_SIZE):
            raise ValueError("unsupported format")
        n, r, p = int(header["n"]), int(header["r"]), int(header["p"])
        if n != _SCRYPT_N or r != _SCRYPT_R or p != _SCRYPT_P:
            raise ValueError("unexpected KDF parameters")
        salt = bytes.fromhex(header["salt"])
        nonce_prefix = bytes.fromhex(header["nonce_prefix"])
        if len(salt) != 16 or len(nonce_prefix) != 8:
            raise ValueError("invalid salt or nonce")
    except Exception as exc:
        raise ProfileBackupError("Unsupported or invalid backup header.") from exc
    key = _derive_key(passphrase, salt, n=n, r=r, p=p)
    aes = AESGCM(key)
    index = 0
    total = 0
    while True:
        length = struct.unpack(">I", _read_exact(source, 4))[0]
        if length == 16:
            encrypted = _read_exact(source, length)
            nonce = nonce_prefix + struct.pack(">I", index)
            try:
                aes.decrypt(nonce, encrypted, header_bytes + b"FINAL" + struct.pack(">I", index))
            except Exception as exc:
                raise ProfileBackupError("Backup authentication failed (wrong passphrase or damaged file).") from exc
            if source.read(1):
                raise ProfileBackupError("Unexpected trailing data after backup terminator.")
            return
        if length < 17 or length > CHUNK_SIZE + 16:
            raise ProfileBackupError("Invalid encrypted chunk length.")
        encrypted = _read_exact(source, length)
        nonce = nonce_prefix + struct.pack(">I", index)
        try:
            plain = aes.decrypt(nonce, encrypted, header_bytes + b"DATA" + struct.pack(">I", index))
        except Exception as exc:
            raise ProfileBackupError("Backup authentication failed (wrong passphrase or damaged file).") from exc
        total += len(plain)
        if total > _MAX_ARCHIVE:
            raise ProfileBackupError("Decrypted backup exceeds the supported size limit.")
        destination.write(plain)
        index += 1
        if index >= 0xFFFFFFFF:
            raise ProfileBackupError("Backup contains too many chunks.")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_snapshot(db_path: Path, key: bytes | None, archive_path: Path, temp_dir: Path) -> dict:
    db_snapshot = temp_dir / "profiles.sqlite3"
    _snapshot_database(db_path, db_snapshot, key)
    validation = _validate_database(db_snapshot, key)
    db_hash = _sha256_file(db_snapshot)
    entries = {"profiles.sqlite3": {"sha256": db_hash, "size": db_snapshot.stat().st_size}}
    if key is not None:
        key_path = temp_dir / "card-number.key"
        key_path.write_bytes(key)
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass
        entries["card-number.key"] = {"sha256": hashlib.sha256(key).hexdigest(), "size": len(key)}
    manifest = {"format": "pdfunlocker-profile-backup", "version": FORMAT_VERSION,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "database_schema_version": validation["schema_version"],
                "profile_count": validation["profile_count"],
                "value_count": validation["value_count"],
                "encrypted_card_count": validation["encrypted_card_count"],
                "entries": entries}
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.write(db_snapshot, "profiles.sqlite3")
        if key is not None:
            zf.write(temp_dir / "card-number.key", "card-number.key")
        zf.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
    return manifest


def _create_backup_unlocked(passphrase: str, destination: str | Path | None = None,
                  *, db_path: str | Path | None = None) -> Path:
    """Create a passphrase-encrypted profile backup and return its path."""
    from pdfunlocker.profiles import store
    source_db = Path(db_path) if db_path is not None else Path(store.DB_PATH)
    key = _read_matching_card_key()
    if key is not None and len(key) != 32:
        raise ProfileBackupError("Card-encryption key must be exactly 32 bytes.")
    target_dir = default_backup_dir()
    if destination is None:
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(target_dir, 0o700)
        except OSError:
            pass
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination_path = target_dir / f"profiles-{stamp}-{secrets.token_hex(3)}.pupb"
    else:
        destination_path = Path(destination).expanduser().resolve()
        target_dir = destination_path.parent
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination_path.exists():
        raise ProfileBackupError(f"Refusing to overwrite existing backup: {destination_path}")
    temp_dir = Path(tempfile.mkdtemp(prefix=".profile-backup-", dir=target_dir))
    try:
        os.chmod(temp_dir, 0o700)
        archive_path = temp_dir / "payload.zip"
        _archive_snapshot(source_db, key, archive_path, temp_dir)
        temp_output = temp_dir / "encrypted.pupb"
        with archive_path.open("rb") as src, temp_output.open("wb") as dst:
            _encrypt_stream(src, dst, passphrase)
            dst.flush()
            os.fsync(dst.fileno())
        # Exclusive final creation prevents accidental overwrite/races.
        fd = os.open(destination_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as out, temp_output.open("rb") as inp:
                shutil.copyfileobj(inp, out, length=CHUNK_SIZE)
                out.flush()
                os.fsync(out.fileno())
        except Exception:
            destination_path.unlink(missing_ok=True)
            raise
        try:
            os.chmod(destination_path, 0o600)
        except OSError:
            pass
        return destination_path
    except ProfileBackupError:
        raise
    except Exception as exc:
        raise ProfileBackupError(f"Could not create profile backup: {exc}") from exc
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



def create_backup(passphrase: str, destination: str | Path | None = None,
                  *, db_path: str | Path | None = None) -> Path:
    """Create a backup while excluding concurrent profile/key operations."""
    from pdfunlocker.profiles import store

    source_db = Path(db_path) if db_path is not None else Path(store.DB_PATH)
    with store.profile_store_lock(source_db):
        with card_crypto._key_file_lock():
            return _create_backup_unlocked(passphrase, destination, db_path=source_db)

def list_backups(directory: str | Path | None = None) -> list[dict]:
    root = Path(directory).expanduser() if directory is not None else default_backup_dir()
    if not root.exists():
        return []
    results = []
    for path in sorted(root.glob("*.pupb"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = path.stat()
            results.append({"path": path, "size": stat.st_size,
                            "modified": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds")})
        except OSError:
            continue
    return results



def _set_private_file_permissions(path: Path) -> None:
    """Require a private 0600 permission mode for sensitive database files."""
    try:
        os.chmod(path, 0o600)
        actual_mode = path.stat().st_mode & 0o777
    except OSError as exc:
        raise ProfileBackupError(
            f"Could not set restrictive permissions on {path}."
        ) from exc

    if actual_mode != 0o600:
        raise ProfileBackupError(
            f"Could not enforce 0600 permissions on {path}."
        )


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    """Read manifest JSON with a strict uncompressed-size bound."""
    info = zf.getinfo("manifest.json")
    if info.file_size > _MAX_MANIFEST:
        raise ProfileBackupError(
            f"Backup manifest exceeds the {_MAX_MANIFEST}-byte limit."
        )

    with zf.open("manifest.json", "r") as stream:
        raw = stream.read(_MAX_MANIFEST + 1)

    if len(raw) > _MAX_MANIFEST:
        raise ProfileBackupError(
            f"Backup manifest exceeds the {_MAX_MANIFEST}-byte limit."
        )

    return json.loads(raw)


def _extract_and_validate(backup_path: Path, passphrase: str, temp_dir: Path) -> tuple[Path, bytes | None, dict]:
    decrypted_zip = temp_dir / "payload.zip"
    try:
        with backup_path.open("rb") as src, decrypted_zip.open("wb") as dst:
            _decrypt_stream(src, dst, passphrase)
        with zipfile.ZipFile(decrypted_zip, "r") as zf:
            names = zf.namelist()
            if len(names) != len(set(names)) or set(names) - {"manifest.json", "profiles.sqlite3", "card-number.key"}:
                raise ProfileBackupError("Backup archive contains unexpected or duplicate files.")
            if not {"manifest.json", "profiles.sqlite3"}.issubset(names):
                raise ProfileBackupError("Backup archive is missing required files.")
            manifest = _read_manifest(zf)
            if not isinstance(manifest, dict):
                raise ProfileBackupError("Backup manifest must be a JSON object.")
            if manifest.get("format") != "pdfunlocker-profile-backup" or manifest.get("version") != FORMAT_VERSION:
                raise ProfileBackupError("Unsupported profile backup manifest.")
            if set(manifest.get("entries", {})) != set(names) - {"manifest.json"}:
                raise ProfileBackupError("Backup manifest does not match archive contents.")
            total_uncompressed = 0
            for name in names:
                info = zf.getinfo(name)
                total_uncompressed += info.file_size
                if info.file_size > _MAX_ARCHIVE or total_uncompressed > _MAX_ARCHIVE:
                    raise ProfileBackupError("Backup archive entries exceed the supported size limit.")
            db_target = temp_dir / "profiles.sqlite3"
            with zf.open("profiles.sqlite3", "r") as src, db_target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=CHUNK_SIZE)
            _set_private_file_permissions(db_target)
            key = zf.read("card-number.key") if "card-number.key" in names else None
            if key is not None and len(key) != 32:
                raise ProfileBackupError("Backup card-encryption key has an invalid length.")
            record = manifest["entries"].get("profiles.sqlite3", {})
            if record.get("size") != db_target.stat().st_size or record.get("sha256") != _sha256_file(db_target):
                raise ProfileBackupError("Backup checksum mismatch: profiles.sqlite3")
            if key is not None:
                record = manifest["entries"].get("card-number.key", {})
                if record.get("size") != len(key) or record.get("sha256") != hashlib.sha256(key).hexdigest():
                    raise ProfileBackupError("Backup checksum mismatch: card-number.key")
            validation = _validate_database(db_target, key)
            if (manifest.get("database_schema_version") != validation["schema_version"]
                    or manifest.get("profile_count") != validation["profile_count"]
                    or manifest.get("value_count") != validation["value_count"]
                    or manifest.get("encrypted_card_count") != validation["encrypted_card_count"]):
                raise ProfileBackupError("Backup manifest metadata does not match the database.")
            return db_target, key, manifest
    except ProfileBackupError:
        raise
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError, KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ProfileBackupError(f"Backup validation failed: {exc}") from exc


def _replace_file_atomically(target: Path, data: bytes | None) -> None:
    if data is None:
        target.unlink(missing_ok=True)
        return
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".restore", dir=target.parent)
    temp = Path(name)
    try:
        try:
            os.fchmod(fd, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        temp.unlink(missing_ok=True)


def _restore_backup_unlocked(backup_path: str | Path, passphrase: str,
                   *, db_path: str | Path | None = None,
                   safety_directory: str | Path | None = None) -> tuple[Path, dict]:
    """Validate fully, create an encrypted safety backup, then replace DB/key."""
    from pdfunlocker.profiles import store
    active_db = Path(db_path) if db_path is not None else Path(store.DB_PATH)
    source = Path(backup_path).expanduser().resolve()
    if not source.is_file():
        raise ProfileBackupError(f"Backup file not found: {source}")
    active_db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_dir = Path(tempfile.mkdtemp(prefix=".profile-restore-", dir=active_db.parent))
    try:
        os.chmod(temp_dir, 0o700)
        staged_db, new_key, manifest = _extract_and_validate(source, passphrase, temp_dir)
        # Validate current data before making the safety copy; if current data is
        # corrupt, refuse a restore that could destroy the only recoverable state.
        current_key = _read_matching_card_key()
        if active_db.exists():
            _validate_database(active_db, current_key)
        else:
            raise ProfileBackupError("Current profile database is missing; refusing in-place restore without a safety snapshot.")
        safety_root = Path(safety_directory) if safety_directory else default_backup_dir()
        safety_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if safety_directory is None:
            try:
                os.chmod(safety_root, 0o700)
            except OSError:
                pass
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safety_path = safety_root / f"profiles-pre-restore-{stamp}-{secrets.token_hex(3)}.pupb"
        _create_backup_unlocked(passphrase, safety_path, db_path=active_db)

        active_key_path = Path(card_crypto.KEY_PATH)
        recovery_key_path = APP_DIR / "backups" / "keys" / "card-number.key"
        rollback_db = temp_dir / "rollback.sqlite3"
        _snapshot_database(active_db, rollback_db, current_key)
        _set_private_file_permissions(rollback_db)
        old_active_key = active_key_path.read_bytes() if active_key_path.is_file() else None
        old_recovery_key = recovery_key_path.read_bytes() if recovery_key_path.is_file() else None
        try:
            # No other PDF Unlocker process may be using the profile DB during this operation.
            for suffix in ("-wal", "-shm"):
                Path(str(active_db) + suffix).unlink(missing_ok=True)
            os.replace(staged_db, active_db)
            _set_private_file_permissions(active_db)
            _replace_file_atomically(active_key_path, new_key)
            _replace_file_atomically(recovery_key_path, new_key)
            _validate_database(active_db, new_key)
        except Exception as exc:
            # Best-effort in-process rollback; encrypted safety package remains
            # available if the filesystem itself prevents rollback.
            try:
                for suffix in ("-wal", "-shm"):
                    Path(str(active_db) + suffix).unlink(missing_ok=True)
                os.replace(rollback_db, active_db)
                _set_private_file_permissions(active_db)
                _replace_file_atomically(active_key_path, old_active_key)
                _replace_file_atomically(recovery_key_path, old_recovery_key)
            except Exception as rollback_exc:
                raise ProfileBackupError(f"Restore failed ({exc}); automatic rollback also failed ({rollback_exc}). Safety backup: {safety_path}") from exc
            raise ProfileBackupError(f"Restore failed and the original files were restored. Safety backup: {safety_path}. Cause: {exc}") from exc
        return safety_path, manifest
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)



def restore_backup(backup_path: str | Path, passphrase: str,
                   *, db_path: str | Path | None = None,
                   safety_directory: str | Path | None = None) -> tuple[Path, dict]:
    """Restore while holding the profile database and card-key locks."""
    from pdfunlocker.profiles import store

    active_db = Path(db_path) if db_path is not None else Path(store.DB_PATH)
    with store.profile_store_lock(active_db):
        with card_crypto._key_file_lock():
            return _restore_backup_unlocked(
                backup_path, passphrase, db_path=active_db,
                safety_directory=safety_directory,
            )

def verify_backup(backup_path: str | Path, passphrase: str) -> dict:
    """Authenticate and validate a backup without touching active profile data.

    The decrypted archive and database are held in a private temporary directory
    and removed before this function returns. No live database or key paths are
    read or written.
    """
    source = Path(backup_path).expanduser().resolve()
    if not source.is_file():
        raise ProfileBackupError(f"Backup file not found: {source}")
    temp_dir = Path(tempfile.mkdtemp(prefix="pdfunlocker-profile-verify-"))
    try:
        try:
            os.chmod(temp_dir, 0o700)
        except OSError:
            pass
        _db_path, _card_key, manifest = _extract_and_validate(source, passphrase, temp_dir)
        return {
            "verified": True,
            "backup_path": source,
            "created_at": manifest.get("created_at"),
            "schema_version": manifest.get("database_schema_version"),
            "profile_count": manifest.get("profile_count"),
            "value_count": manifest.get("value_count"),
            "encrypted_card_count": manifest.get("encrypted_card_count"),
            "includes_card_key": "card-number.key" in manifest.get("entries", {}),
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
