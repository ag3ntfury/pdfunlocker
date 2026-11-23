"""Interactive profile management CLI."""

import sqlite3
from pathlib import Path

from pdfunlocker.config.paths import resolve_paths
from pdfunlocker.profiles.store import (
    connect,
    create_profile,
    delete_profile,
    get_profile,
    initialize_database,
    list_profiles,
    load_field_registry,
    next_profile_id,
    remove_profile_value,
    reorder_profile,
    set_profile_enabled,
    set_profile_value,
    _normalize_and_validate,
)


def paths(root=None):
    if root is None:
        root = Path(__file__).resolve().parents[3]
    else:
        root = Path(root).expanduser().resolve()
    resolved = resolve_paths(root)
    return {
        "root": root,
        "database": resolved["database"],
        "template": root / "templates" / "profile" / "default_profile_template.yml",
    }


def database_ready(database):
    return database.is_file()


def require_database(database):
    if not database_ready(database):
        raise RuntimeError("No profiles exist. Use 'profile add' first.")


def prompt(message):
    try:
        return input(message).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nReturning to profile menu.")
        return None


def _collect_initial_profile_values(profile_id, database, template, fields):
    """Collect optional profile fields in template order.

    Single-value fields are prompted once. Multiple-value fields repeat until
    Enter is pressed. Ctrl+C/EOF stops collection but keeps the already-created
    profile and any values collected so far.
    """
    print("\n===== PROFILE DETAILS =====")
    print("Press Enter to skip an optional field.")
    print("For multiple-value fields, press Enter when you have finished that field.")

    for field_id, field in fields.items():
        label = field["name"].replace("_", " ").title()

        if field["multiplicity"] == "M":
            print(f"\n{label} (multiple; optional)")
            while True:
                value = prompt(f"  {label} value (Enter to finish): ")
                if value is None:
                    print("Profile details entry stopped. Saved values are retained.")
                    return
                if not value:
                    break
                try:
                    value_id = set_profile_value(
                        database, template, profile_id, field_id, value
                    )
                    print(f"  Saved: {value_id}")
                except ValueError as error:
                    print(f"  Not saved: {error}")
        else:
            while True:
                value = prompt(f"{label} (optional): ")
                if value is None:
                    print("Profile details entry stopped. Saved values are retained.")
                    return
                if not value:
                    break
                try:
                    value_id = set_profile_value(
                        database, template, profile_id, field_id, value
                    )
                    print(f"  Saved: {value_id}")
                    break
                except ValueError as error:
                    print(f"  Not saved: {error}")


def create_profile_interactive(root=None):
    p = paths(root)

    print("\n===== CREATE PROFILE =====")
    initialize_database(p["database"])

    # Preview only: this does not update app_metadata or consume an ID.
    preview_id = next_profile_id(p["database"])
    print(f"Next available profile ID: {preview_id}")

    name = prompt("Profile name: ")
    if name is None or not name:
        print("Cancelled. No profile created; the profile ID remains available.")
        return None

    # The ID becomes permanent only after the accepted name is committed.
    profile_id = create_profile(p["database"], name)
    profile, _ = get_profile(p["database"], profile_id)

    print(f"\nProfile created: {profile_id}")
    print(f"Name: {profile['name']}")

    fields = load_field_registry(p["template"])
    _collect_initial_profile_values(
        profile_id, p["database"], p["template"], fields
    )

    print(f"\nProfile saved: {profile_id}")
    return profile_id


def command_add(args):
    create_profile_interactive()


def command_list(args):
    p = paths()

    if not database_ready(p["database"]):
        print("No profiles found.")
        return

    profiles = list_profiles(p["database"], include_disabled=False)

    if not profiles:
        print("No profiles found.")
        return

    print(f"\n{'ID':<16} {'ORDER':<7} {'STATUS':<10} NAME")
    print("-" * 65)

    for profile in profiles:
        status = "Enabled" if profile["enabled"] else "Disabled"
        print(
            f"{profile['profile_id']:<16} "
            f"{profile['execution_order']:<7} "
            f"{status:<10} {profile['name']}"
        )


def command_show(args):
    p = paths()
    require_database(p["database"])

    profile, values = get_profile(p["database"], args.profile_id)
    fields = load_field_registry(p["template"])

    grouped = {}
    for value in values:
        grouped.setdefault(value["field_id"], []).append(value)

    print(f"\n===== {profile['profile_id']} =====")
    print(f"Name: {profile['name']}")
    print(f"Status: {'Enabled' if profile['enabled'] else 'Disabled'}")
    print(f"Execution order: {profile['execution_order']}")

    for category, entries in _categories(fields).items():
        print(f"\n--- {category.upper()} ---")

        for field_id, field in entries:
            print(f"{field_id}  {field['name']}")

            saved = grouped.get(field_id, [])
            if not saved:
                print("    (empty)")
                continue

            for value in saved:
                print(f"    {value['value_id']}: {value['value']}")


def _categories(fields):
    grouped = {}
    for field_id, field in fields.items():
        grouped.setdefault(field["category"], []).append((field_id, field))
    return grouped


def _choose_field(fields):
    print("\nAvailable fields:")

    for field_id, field in fields.items():
        multiple = "multiple" if field["multiplicity"] == "M" else "single"
        print(f"  {field_id}  {field['name']} ({multiple})")

    field_id = prompt("\nField ID: ")

    if field_id is None:
        return None

    if field_id not in fields:
        print("Invalid field ID.")
        return None

    return field_id


def _add_or_update_value(profile_id, fields, database, template):
    field_id = _choose_field(fields)
    if field_id is None:
        return

    field = fields[field_id]
    value = prompt(f"Enter {field['name']}: ")

    if value is None or not value:
        print("No value entered. Nothing changed.")
        return

    try:
        value_id = set_profile_value(
            database, template, profile_id, field_id, value
        )
        print(f"Saved: {value_id}")
    except ValueError as error:
        print(f"Not saved: {error}")


def _change_existing_value(profile_id, database, template, fields):
    _, values = get_profile(database, profile_id)

    if not values:
        print("This profile has no saved values.")
        return

    print("\nSaved values:")
    for item in values:
        field = fields[item["field_id"]]
        print(
            f"  {item['value_id']} — {field['name']}: {item['value']}"
        )

    value_id = prompt("\nValue ID to change: ")
    if value_id is None or not value_id:
        return

    selected = next(
        (item for item in values if item["value_id"] == value_id),
        None,
    )

    if selected is None:
        print("Value ID not found.")
        return

    new_value = prompt("New value: ")
    if new_value is None or not new_value:
        print("No change made.")
        return

    field = fields[selected["field_id"]]

    try:
        normalized = _normalize_and_validate(field, new_value)

        with connect(database) as db:
            duplicate = db.execute("""
                SELECT 1 FROM profile_values
                WHERE profile_id = ?
                  AND field_id = ?
                  AND value = ?
                  AND value_id != ?
            """, (
                profile_id,
                selected["field_id"],
                normalized,
                value_id,
            )).fetchone()

            if duplicate:
                raise ValueError("This value already exists in the field.")

            db.execute("""
                UPDATE profile_values
                SET value = ?, updated_at = ?
                WHERE profile_id = ? AND value_id = ?
            """, (
                normalized,
                __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(timespec="seconds"),
                profile_id,
                value_id,
            ))

        print(f"Updated: {value_id}")

    except ValueError as error:
        print(f"Not saved: {error}")


def _remove_existing_value(profile_id, database):
    _, values = get_profile(database, profile_id)

    if not values:
        print("This profile has no saved values.")
        return

    print("\nSaved values:")
    for item in values:
        print(f"  {item['value_id']}: {item['value']}")

    value_id = prompt("\nValue ID to remove: ")
    if value_id is None or not value_id:
        return

    try:
        remove_profile_value(database, profile_id, value_id)
        print(f"Removed: {value_id}")
    except ValueError as error:
        print(error)


def _rename_profile(profile_id, database):
    name = prompt("New profile name: ")

    if name is None or not name:
        print("Name unchanged.")
        return

    with connect(database) as db:
        result = db.execute("""
            UPDATE profiles
            SET name = ?, updated_at = datetime('now')
            WHERE profile_id = ?
        """, (name, profile_id))

        if result.rowcount == 0:
            raise ValueError(f"Profile not found: {profile_id}")

    print("Profile name updated.")


def _toggle_profile(profile_id, database):
    profile, _ = get_profile(database, profile_id)
    enabled = not bool(profile["enabled"])

    set_profile_enabled(database, profile_id, enabled)
    print(f"Profile {'enabled' if enabled else 'disabled'}.")


def _change_order(profile_id, database):
    profiles = list_profiles(database)

    print("\nCurrent execution order:")
    for item in profiles:
        print(f"  {item['execution_order']}. {item['profile_id']} — {item['name']}")

    position = prompt("New position: ")
    if position is None or not position:
        return

    try:
        reorder_profile(database, profile_id, int(position))
        print("Execution order updated.")
    except (ValueError, TypeError) as error:
        print(f"Invalid position: {error}")


def profile_editor(profile_id, root=None):
    p = paths(root)
    database = p["database"]
    template = p["template"]
    fields = load_field_registry(template)

    while True:
        profile, _ = get_profile(database, profile_id)

        print(f"\n===== PROFILE: {profile['name']} =====")
        print(f"ID: {profile_id}")
        print(f"Status: {'Enabled' if profile['enabled'] else 'Disabled'}")
        print("""
1. Add a field value
2. Change an existing value
3. Remove a value
4. Change profile name
5. Enable / Disable profile
6. Change execution order
0. Finish
""")

        choice = prompt("Select: ")

        if choice is None or choice == "0":
            print("Profile saved.")
            return

        try:
            if choice == "1":
                _add_or_update_value(profile_id, fields, database, template)
            elif choice == "2":
                _change_existing_value(profile_id, database, template, fields)
            elif choice == "3":
                _remove_existing_value(profile_id, database)
            elif choice == "4":
                _rename_profile(profile_id, database)
            elif choice == "5":
                _toggle_profile(profile_id, database)
            elif choice == "6":
                _change_order(profile_id, database)
            else:
                print("Invalid selection.")

        except (ValueError, sqlite3.Error, OSError) as error:
            print(f"Operation failed: {error}")


def command_edit(args):
    p = paths()
    require_database(p["database"])
    get_profile(p["database"], args.profile_id)
    profile_editor(args.profile_id)


def command_delete(args):
    p = paths()
    require_database(p["database"])

    profile, _ = get_profile(p["database"], args.profile_id)

    print(f"\nDelete profile {profile['profile_id']} ({profile['name']})?")
    print("All saved values belonging to this profile will also be deleted.")

    answer = prompt("Type DELETE to confirm: ")

    if answer != "DELETE":
        print("Deletion cancelled.")
        return

    delete_profile(p["database"], args.profile_id)
    print(f"Deleted: {args.profile_id}")


def add_profile_commands(subparsers):
    parser = subparsers.add_parser(
        "profile",
        help="Manage profiles",
        description="Manage PDF Unlocker profiles.",
    )

    commands = parser.add_subparsers(
        dest="profile_command",
        required=True,
    )

    add = commands.add_parser("add", help="Create a profile")
    add.set_defaults(func=command_add)

    listing = commands.add_parser("list", help="List profiles")
    listing.set_defaults(func=command_list)

    show = commands.add_parser("show", help="View a profile")
    show.add_argument("profile_id")
    show.set_defaults(func=command_show)

    edit = commands.add_parser("edit", help="Edit a profile interactively")
    edit.add_argument("profile_id")
    edit.set_defaults(func=command_edit)

    delete = commands.add_parser("delete", help="Delete a profile")
    delete.add_argument("profile_id")
    delete.set_defaults(func=command_delete)

    return parser
