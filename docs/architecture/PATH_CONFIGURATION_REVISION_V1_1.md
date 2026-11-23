# PDF Unlocker — Path Configuration Revision v1.1

**Status:** Approved by project owner

This revision defines platform-specific PDF library defaults while keeping
the application installation and PDF library independent.

## Defaults

- Application installation: `~/pdfunlocker` on Android/Termux and Linux.
- Android/Termux PDF library: `/storage/emulated/0/PDFUnlocker`.
- Linux PDF library: `~/PDFunlocker`.

The setup wizard displays these defaults and allows the user to enter different
absolute or home-relative paths. The paths are expanded and resolved before
validation and are saved independently in `config/settings.json`.

## Separation and safety

- The application directory contains source/runtime application data,
  configuration, SQLite databases, profiles, rules, logs, temporary files,
  exports and backups.
- The PDF library contains PDF workflow folders only.
- The two paths must not be equal or nested inside one another.
- Re-running setup can change either path independently.
- Existing destination settings are preserved when application files are
  copied into an installation directory.
- Existing database and profile data are not copied over or deleted by the
  application file-copy operation.
- The setup wizard validates read/write/execute access before creating PDF
  library subdirectories.
- The Android shared-storage library is the default and is not migrated by
  setup. Existing PDF files remain in place.

## Production installation

When setup is launched from a development checkout, application files are
copied to the selected installation directory. The development checkout is
not renamed, moved or deleted. The launcher command remains `pdfunlocker`
regardless of the chosen installation directory.

This revision records the platform-specific defaults and supersedes only the
PDF library default-location detail in the v1 structure specification. Other
approved v1 file-handling and processing requirements remain unchanged.
