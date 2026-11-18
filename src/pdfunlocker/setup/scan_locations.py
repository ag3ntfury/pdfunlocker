import os
import shlex
from pathlib import Path


ANDROID_STORAGE = Path("/storage/emulated/0")

PSEUDO_FILESYSTEMS = {
    "proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup",
    "cgroup2", "pstore", "securityfs", "debugfs", "tracefs",
    "configfs", "fusectl", "mqueue", "hugetlbfs", "rpc_pipefs",
    "autofs", "binfmt_misc",
}

SYSTEM_MOUNTS = ("/proc", "/sys", "/dev", "/run")


def is_android():
    prefix = os.environ.get("PREFIX", "")
    return (
        "com.termux" in prefix
        or prefix.startswith("/data/data/com.termux/")
        or Path("/data/data/com.termux/files/usr").exists()
    )


def resolve_directory(value):
    path = Path(value).expanduser()
    return path.resolve(strict=True)


def is_inside(path, parent):
    try:
        return os.path.commonpath([str(path), str(parent)]) == str(parent)
    except ValueError:
        return False


def add_location(locations, candidate):
    """Add a location while avoiding duplicate or nested scan roots."""
    if any(is_inside(candidate, existing) for existing in locations):
        return False

    locations[:] = [
        existing for existing in locations
        if not is_inside(existing, candidate)
    ]
    locations.append(candidate)
    return True


def validate_directory(value):
    try:
        path = resolve_directory(value)
    except (OSError, RuntimeError, ValueError):
        return None, "Folder does not exist or cannot be accessed."

    if not path.is_dir():
        return None, "The selected path is not a directory."

    if not os.access(path, os.R_OK | os.X_OK):
        return None, "Folder is not readable."

    return path, None


def android_scan_locations(pdf_storage):
    print("\n===== ANDROID SCAN LOCATIONS =====")
    print(f"Default location: {ANDROID_STORAGE}")
    print("Press ENTER to scan the entire internal shared storage.")
    print("Or enter a folder name, such as Download or Documents.")
    print("You can also enter a subfolder, such as WhatsApp/Media.")

    while True:
        choice = input("\nLocation: ").strip()

        if not choice:
            locations = [ANDROID_STORAGE.resolve()]
            print(f"Selected entire storage: {locations[0]}")
            return locations

        candidate_input = Path(choice).expanduser()

        if candidate_input.is_absolute():
            candidate = candidate_input
        else:
            candidate = ANDROID_STORAGE / candidate_input

        path, error = validate_directory(candidate)

        if error:
            print(f"Invalid location: {error}")
            continue

        if not is_inside(path, ANDROID_STORAGE.resolve()):
            print("Please choose a folder inside /storage/emulated/0.")
            continue

        if path == pdf_storage or is_inside(path, pdf_storage):
            print("PDF Unlocker storage cannot be selected for scanning.")
            continue

        return android_additional_locations(path)


def android_additional_locations(first_location):
    locations = [first_location]

    print(f"Added: {first_location}")
    print("Enter another folder name, or press ENTER to finish.")

    while True:
        choice = input("\nNext folder (ENTER to finish): ").strip()

        if not choice:
            break

        candidate_input = Path(choice).expanduser()
        candidate = (
            candidate_input
            if candidate_input.is_absolute()
            else ANDROID_STORAGE / candidate_input
        )

        path, error = validate_directory(candidate)

        if error:
            print(f"Invalid location: {error}")
            continue

        if not is_inside(path, ANDROID_STORAGE.resolve()):
            print("Please choose a folder inside /storage/emulated/0.")
            continue

        if path == ANDROID_STORAGE.resolve():
            print("The entire storage is already covered by this selection.")
            continue

        added = add_location(locations, path)

        if added:
            print(f"Added: {path}")
        else:
            print("This folder is already covered by another selected location.")

    return locations


def decode_mount_path(value):
    return (
        value.replace("\\040", " ")
        .replace("\\011", "\t")
        .replace("\\012", "\n")
        .replace("\\134", "\\")
    )


def get_linux_mounts():
    mounts = []
    seen = set()

    try:
        with open("/proc/self/mounts", encoding="utf-8") as file:
            for line in file:
                fields = shlex.split(line)

                if len(fields) < 3:
                    continue

                mountpoint = Path(decode_mount_path(fields[1]))
                filesystem = fields[2]

                if filesystem in PSEUDO_FILESYSTEMS:
                    continue

                try:
                    mountpoint = mountpoint.resolve(strict=True)
                except (OSError, RuntimeError):
                    continue

                if not mountpoint.is_dir():
                    continue

                if not os.access(mountpoint, os.R_OK | os.X_OK):
                    continue

                if any(
                    mountpoint == Path(item)
                    or is_inside(mountpoint, Path(item))
                    for item in SYSTEM_MOUNTS
                ):
                    continue

                if mountpoint in seen:
                    continue

                seen.add(mountpoint)
                mounts.append(mountpoint)

    except OSError:
        pass

    if Path("/").resolve() not in seen:
        mounts.insert(0, Path("/").resolve())

    return sorted(mounts, key=lambda path: (len(str(path)), str(path)))


def linux_scan_locations(pdf_storage):
    print("\n===== LINUX SCAN LOCATIONS =====")
    print("1. Scan mounted partitions")
    print("2. Choose individual folders")

    while True:
        choice = input("Select option [1]: ").strip() or "1"

        if choice in ("1", "2"):
            break

        print("Please enter 1 or 2.")

    if choice == "1":
        mounts = get_linux_mounts()

        print("\nAvailable accessible mounted locations:")
        for index, mount in enumerate(mounts, start=1):
            print(f"  {index}. {mount}")

        print("\nPress ENTER to select all listed locations.")
        print("Or enter partition numbers separated by commas.")

        while True:
            selection = input("Partitions: ").strip()

            if not selection:
                locations = mounts[:]
                break

            try:
                numbers = [
                    int(item.strip())
                    for item in selection.split(",")
                ]

                if not numbers or any(
                    number < 1 or number > len(mounts)
                    for number in numbers
                ):
                    raise ValueError

                locations = []
                for number in numbers:
                    add_location(locations, mounts[number - 1])
                break

            except ValueError:
                print("Invalid selection. Example: 1,2,3")

    else:
        locations = []

        print("\nEnter absolute folder paths.")
        print("Press ENTER when you have finished.")

        while True:
            value = input("Folder: ").strip()

            if not value:
                if locations:
                    break
                print("Please select at least one folder.")
                continue

            path, error = validate_directory(value)

            if error:
                print(f"Invalid location: {error}")
                continue

            if add_location(locations, path):
                print(f"Added: {path}")
            else:
                print("This folder is already covered by another selection.")

    if pdf_storage in locations:
        locations.remove(pdf_storage)

    print("\nSelected scan locations:")
    for path in locations:
        print(f"  {path}")

    return locations


def select_scan_locations(environment, pdf_storage):
    pdf_storage = Path(pdf_storage).expanduser().resolve()

    if environment == "android":
        locations = android_scan_locations(pdf_storage)
    else:
        locations = linux_scan_locations(pdf_storage)

    locations = [
        path for path in locations
        if path != pdf_storage and not is_inside(path, pdf_storage)
    ]

    if not locations:
        raise RuntimeError("No valid scan locations were selected.")

    # Record nested selected mount points as per-location exclusions.
    location_exclusions = {}

    for parent in locations:
        nested = [
            str(child)
            for child in locations
            if child != parent and is_inside(child, parent)
        ]
        if nested:
            location_exclusions[str(parent)] = nested

    exclusions = [str(pdf_storage)]

    if environment == "linux":
        exclusions.extend(SYSTEM_MOUNTS)

    return {
        "locations": [str(path) for path in locations],
        "recursive": True,
        "follow_symlinks": False,
        "exclude_paths": sorted(set(exclusions)),
        "location_exclusions": location_exclusions,
        "file_extensions": [".pdf"],
        "duplicate_detection": "sha256",
        "source_files": "never_modify",
    }
