# PDF Unlocker v1.3 — Path, Installer and Scan Setup

## Scope

This revision completes installation path selection, fixed directory creation,
public output/export folder creation, legacy database path migration, and scan
location configuration. It deliberately stops before profile setup. It does not
create a database schema, create profiles, change profile values, reorder
profiles, or modify profile priority.

## Defaults

### Android (Termux)

- Private application root: `$HOME/.pdfunlocker`
- Public PDF storage root: `/storage/emulated/0/Documents/PDFUnlocker`
- Processed output: `Documents/PDFUnlocker/Processed`
- Exports: `Documents/PDFUnlocker/Export`
- Default scan root: `/storage/emulated/0` (accessible shared internal storage)

### Linux

- Application root: `~/.pdfunlocker`
- Public PDF storage root: `~/Documents/PDFUnlocker`
- Processed output: `~/Documents/PDFUnlocker/Processed`
- Exports: `~/Documents/PDFUnlocker/Export`
- Default scan root: the current user's home directory, not `/`.

## Fixed private structure

The installer creates `config`, `database`, `profiles`, `rules`, `learning`,
`storage/{Original,Locked,Unlocked,Corrupted,Unsupported,Duplicates}`,
`queue/{Pending,Processing,Completed}`, `backups/{Database,Configuration}`,
`logs/{Application,Scanner,Processing}`, `reports`, `temp`, and `cache` under
the selected application root. These internal folders are not individually
configurable.

## Public structure

The selected public PDF storage root contains `Processed/` and `Export/`.
Export contains `Database/{Manual,Automatic}`, `Profiles`, `Reports`, `Logs`,
and `PDF-Records/{Original,Locked,Unlocked,Corrupted,Unsupported,Duplicates}`.
The installer creates directories only; it does not populate PDF-Records with
copies of source PDFs.

Only successfully unlocked and verified PDFs are intended for publication in
`Processed/`. Original, locked, failed, corrupted, unsupported and intermediate
files remain in private application storage when later processing stages use
those stores.

## Installer modes

1. Default: no path questions. Uses platform defaults and scans the entire
   accessible shared internal storage on Android or the user's home directory
   on Linux.
2. Manual: asks for the application root, public PDF storage root, and scan
   locations. Processed and Export are derived under the selected public root.

## Scan safeguards

- Recursive PDF discovery.
- Symlink following disabled.
- SHA-256 duplicate detection.
- Source files are never modified.
- Application and public output roots are excluded from scanning.
- Linux pseudo/system mounts are excluded.
- Android whole-storage means accessible shared storage, not other apps' private
  sandboxes.

## Existing database migration

The active v1.3 database path is `<application-root>/database/pdfunlocker.db`.
If a single legacy database exists under `<application-root>/data/database/`,
the installer copies it using SQLite's online backup API and integrity checks.
The legacy source remains untouched. If multiple candidates or conflicting
source/destination databases exist, setup stops rather than choosing one.

## Profile boundary

The installer does not initialize a database schema or execute profile commands.
It preserves existing setup flags and profile data. Profile creation, profile
ordering and profile configuration remain a separate later project phase.

### v1.3.1 regression correction — source settings isolation

When installing into a separate destination, the installer reads settings only
from that destination. It must not fall back to the source checkout's
`config/settings.json`, because that file may contain machine-specific paths or
stale setup-stage flags such as `profile_configured` and `completed`. Existing
destination settings remain preserved. A fresh destination starts with fresh
setup-stage flags and still stops after scan configuration.
