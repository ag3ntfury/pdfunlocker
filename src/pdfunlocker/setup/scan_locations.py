"""Platform-specific, read-only PDF scan-location configuration."""

import os
from pathlib import Path


ANDROID_STORAGE = Path("/storage/emulated/0")
SYSTEM_MOUNTS = ("/proc", "/sys", "/dev", "/run")


def is_android():
    prefix = os.environ.get("PREFIX", "")
    return (
        "com.termux" in prefix
        or prefix.startswith("/data/data/com.termux/")
        or Path("/data/data/com.termux/files/usr").exists()
    )


def is_inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except (ValueError, OSError, RuntimeError):
        return False


def resolve_directory(value):
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise ValueError("Symbolic-link scan roots are not allowed.")
    return raw.resolve(strict=True)


def validate_directory(value):
    try:
        path = resolve_directory(value)
    except (OSError, RuntimeError, ValueError):
        return None, "Folder does not exist, is a symbolic link, or cannot be accessed."

    if not path.is_dir():
        return None, "The selected path is not a directory."

    if not os.access(path, os.R_OK | os.X_OK):
        return None, "Folder is not readable."

    return path, None


def add_location(locations, candidate):
    """Add a scan root while removing duplicate or nested roots."""
    candidate = Path(candidate).resolve()
    if any(is_inside(candidate, existing) for existing in locations):
        return False

    locations[:] = [
        Path(existing).resolve()
        for existing in locations
        if not is_inside(existing, candidate)
    ]
    locations.append(candidate)
    return True


def android_scan_locations(pdf_storage, home=None):
    """Show actual top-level shared-storage folders and accept numbered choices.

    Empty input means the complete shared internal storage. Termux HOME is
    deliberately not included.
    """
    storage = ANDROID_STORAGE.resolve(strict=True)
    pdf_storage = Path(pdf_storage).expanduser().resolve()

    entries = sorted(
        (
            item for item in storage.iterdir()
            if item.is_dir()
            and not item.is_symlink()
            and os.access(item, os.R_OK | os.X_OK)
        ),
        key=lambda item: item.name.casefold(),
    )

    print("\n===== ANDROID SCAN LOCATIONS =====")
    print(f"Default: Entire shared internal storage ({storage})")
    print("\nAvailable folders:")

    for index, folder in enumerate(entries, start=1):
        print(f"  {index}. {folder.name}")

    print("\nEnter one number or multiple numbers separated by commas (example: 3,5,2,7).")
    print("Press ENTER without a number to scan the entire shared internal storage.")

    while True:
        choice = input("\nFolder numbers: ").strip()

        if not choice:
            print(f"Selected entire shared internal storage: {storage}")
            return [storage]

        try:
            numbers = [int(token.strip()) for token in choice.split(",")]
            if not numbers or any(number < 1 or number > len(entries) for number in numbers):
                raise ValueError
        except ValueError:
            print(f"Invalid selection. Enter numbers from 1 to {len(entries)}, separated by commas.")
            continue

        selected = []
        for number in numbers:
            folder = entries[number - 1].resolve()
            if folder == pdf_storage or is_inside(folder, pdf_storage):
                print(f"Skipped PDF Unlocker output folder: {folder}")
                continue
            if add_location(selected, folder):
                print(f"Added: {folder}")
            else:
                print(f"Already covered by another selection: {folder}")

        if selected:
            return selected

        print("No eligible folders selected. Please choose again.")


def linux_scan_locations(pdf_storage, home=None):
    """Use HOME when no custom paths are entered; otherwise use custom paths only."""
    home = Path(home or Path.home()).expanduser().resolve(strict=True)
    pdf_storage = Path(pdf_storage).expanduser().resolve()

    print("\n===== LINUX SCAN LOCATIONS =====")
    print(f"Default scan location:\n  {home}")
    print("Press ENTER to use the default location, or enter a full directory path.")
    print("Add paths one at a time. Press ENTER on an empty prompt to finish.")

    locations = []
    while True:
        value = input("\nFolder: ").strip()

        if not value:
            if locations:
                break
            print(f"Using default scan location: {home}")
            return [home]

        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            print("Please enter an absolute directory path.")
            continue

        path, error = validate_directory(candidate)
        if error:
            print(f"Invalid location {value}: {error}")
            continue

        if path == pdf_storage or is_inside(path, pdf_storage):
            print("PDF Unlocker public output cannot be selected as a scan root.")
            continue

        if add_location(locations, path):
            print(f"Added: {path}")
        else:
            print(f"Already covered by another selected location: {path}")

    print("\nSelected custom scan locations:")
    for path in locations:
        print(f"  {path}")
    return locations


def select_scan_locations(environment, pdf_storage, installation=None, default=False, home=None):
    """Build the scanner configuration for Android or Linux."""
    pdf_storage = Path(pdf_storage).expanduser().resolve()
    installation = Path(installation).expanduser().resolve() if installation else None
    home = Path(home or Path.home()).expanduser().resolve()

    if environment == "android":
        if default:
            locations = [ANDROID_STORAGE.resolve(strict=True)]
        else:
            locations = android_scan_locations(pdf_storage, home=home)
    elif environment == "linux":
        if default:
            locations = [home.resolve(strict=True)]
        else:
            locations = linux_scan_locations(pdf_storage, home=home)
    else:
        raise RuntimeError(f"Unsupported scan environment: {environment}")

    # Remove scan roots that are themselves generated output or private app data.
    locations = [
        Path(path).resolve()
        for path in locations
        if Path(path).resolve() != pdf_storage
        and not is_inside(Path(path).resolve(), pdf_storage)
        and not (
            installation
            and (
                Path(path).resolve() == installation
                or is_inside(Path(path).resolve(), installation)
            )
        )
    ]

    if not locations:
        raise RuntimeError("No valid scan locations were selected.")

    # Ensure stable, non-overlapping roots even if a caller supplied duplicates.
    normalized = []
    for location in locations:
        add_location(normalized, location)
    locations = normalized

    exclusions = {str(pdf_storage)}
    if installation:
        exclusions.add(str(installation))
    if environment == "linux":
        exclusions.update(SYSTEM_MOUNTS)
        for relative in (".cache", ".local/share/Trash", ".local/share/virtualenvs"):
            exclusions.add(str(home / relative))

    location_exclusions = {}
    for parent in locations:
        nested = [
            str(child) for child in locations
            if child != parent and is_inside(child, parent)
        ]
        if nested:
            location_exclusions[str(parent)] = nested

    return {
        "locations": [str(path) for path in locations],
        "recursive": True,
        "follow_symlinks": False,
        "exclude_paths": sorted(exclusions),
        "location_exclusions": location_exclusions,
        "file_extensions": [".pdf"],
        "duplicate_detection": "sha256",
        "source_files": "never_modify",
    }
