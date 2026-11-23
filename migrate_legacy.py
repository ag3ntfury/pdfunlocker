from pathlib import Path
import hashlib
import shutil
import sys

ROOT = Path("/storage/emulated/0/PDFUnlocker")

MAPPING = {
    ROOT / "inbox": ROOT / "Inbox",
    ROOT / "output" / "original": ROOT / "Original",
    ROOT / "output" / "unlocked": ROOT / "Unlocked",
    ROOT / "output" / "locked": ROOT / "Locked",
    ROOT / "output" / "corrupted": ROOT / "Unsupported",
    ROOT / "output" / "Duplicates": ROOT / "Duplicates",
}

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def main():
    total = 0

    for source_dir, destination_dir in MAPPING.items():
        if not source_dir.exists():
            continue

        destination_dir.mkdir(parents=True, exist_ok=True)

        for source in sorted(source_dir.rglob("*")):
            if not source.is_file():
                continue

            source_hash = sha256(source)
            destination = destination_dir / source.name

            if destination.exists():
                if destination.is_file() and sha256(destination) == source_hash:
                    source.unlink()
                    total += 1
                    print(f"IDENTICAL: {source.name}")
                    continue

                number = 1
                while True:
                    destination = destination_dir / (
                        f"{source.stem}__migrated_{number}{source.suffix}"
                    )
                    if not destination.exists():
                        break
                    if destination.is_file() and sha256(destination) == source_hash:
                        break
                    number += 1

                if destination.exists():
                    source.unlink()
                    total += 1
                    print(f"IDENTICAL: {source.name}")
                    continue

            temporary = destination.with_name(destination.name + ".migrating")

            try:
                shutil.copy2(source, temporary)

                if sha256(temporary) != source_hash:
                    raise RuntimeError(f"Verification failed: {source}")

                temporary.replace(destination)
                source.unlink()
                total += 1
                print(f"MOVED: {source.name}")

            finally:
                if temporary.exists():
                    temporary.unlink()

    for source_dir in MAPPING:
        if source_dir.exists():
            remaining = [p for p in source_dir.rglob("*") if p.is_file()]
            if remaining:
                raise RuntimeError(f"Files remain in {source_dir}")

    for source_dir in MAPPING:
        if source_dir.exists():
            shutil.rmtree(source_dir)
            print(f"REMOVED: {source_dir}")

    print(f"\nMigration completed. Files processed: {total}")

    for name in ("Inbox", "Original", "Unlocked",
                 "Locked", "Unsupported", "Duplicates"):
        folder = ROOT / name
        count = sum(1 for p in folder.rglob("*") if p.is_file())
        print(f"{name}: {count} files")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nMIGRATION STOPPED: {error}", file=sys.stderr)
        sys.exit(1)
