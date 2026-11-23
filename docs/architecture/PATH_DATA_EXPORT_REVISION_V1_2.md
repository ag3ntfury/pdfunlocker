# PDF Unlocker — Path, Data and Export Architecture v1.2

**Status:** User-approved architecture revision
**Supersedes:** Path defaults and data placement in Structure Specification v1
**Scope:** Linux, Android / Termux

## 1. Installation directory

The default application installation is `~/.pdfunlocker` on both Linux and Android / Termux. It contains application source, templates, rules, configuration, tests and documentation. The installation path remains configurable.

## 2. Persistent application data

The default persistent data directory is `~/.pdfunlocker/data/`. It is independently configurable and may be placed elsewhere by the user. The default layout is:

```text
.pdfunlocker/data/
├── database/
│   └── pdfunlocker.db
├── profiles/
├── learning/
└── backups/             # private recovery snapshots
```

The active SQLite database and profile / learning state are private application data, not PDF-library content. Do not store real profile values or runtime databases in public Git.

## 3. PDF library defaults

The PDF library is independently configurable.

- Android / Termux: `/storage/emulated/0/PDFUnlocker/`
- Linux: `~/PDFUnlocker/`

The existing Android shared-storage library is not moved, renamed, deleted or automatically merged during a path change.

## 4. User-accessible exports

Database exports and reports are placed inside the PDF library so they are accessible from file managers and other applications:

```text
PDFUnlocker/Export/
├── Database/
│   ├── Manual/
│   └── Automatic/
├── Reports/
├── Logs/
└── Profiles/
```

The active database is never stored in `Export/`. Exports are copies. SQLite snapshots must use SQLite's online backup API, pass `PRAGMA integrity_check`, and be written atomically. A private recovery snapshot is retained under `data/backups/` separately from the user-accessible export.

## 5. Configuration

The following paths are independently configurable and stored as absolute resolved paths:

- `paths.installation`
- `paths.data`
- `paths.pdf_storage`
- `paths.exports` (defaults to `<pdf_storage>/Export`)

The default data path may live inside the installation directory. Data and PDF-library directories must not overlap. Installation and PDF-library directories must not overlap.

## 6. Migration and safety

- Changing a path must not move or delete existing PDFs.
- Changing the data path must not silently create an empty replacement database when an existing database is present.
- A data migration must use a verified SQLite backup / restore process, preserve the source, and validate the destination before switching configuration.
- Database export must fail if the active database is missing; it must never create an empty export that looks valid.
- Private profile values, database files, HMAC keys and recovery backups must be excluded from Git.
- The installer must preserve existing `config/settings.json` and existing user data.

## 7. CLI

Manual database export:

```bash
pdfunlocker database export
```

Automatic-folder export:

```bash
pdfunlocker database export --automatic
```

The automatic flag selects the user-accessible `Export/Database/Automatic/` destination. Scheduling and retention policies are a subsequent module, not implied by this command.
