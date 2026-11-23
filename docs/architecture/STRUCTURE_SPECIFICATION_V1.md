# PDF Unlocker — Structure Specification v1

**Version:** 1.0  
**Status:** Approved baseline  
**Release:** Alpha v1

This document records the agreed application structure, storage locations, setup wizard, PDF scanning and file-handling requirements.

Future changes must be documented as revisions. Do not silently change approved requirements.

---

## 1. Application installation

Default installation directory:

```text
~/pdfunlocker/
```

The application directory contains application code, configuration, database, profiles, logs, temporary files and exports.

```text
pdfunlocker/
├── src/
├── templates/
│   ├── profile/
│   └── rules/
├── rules/
├── config/
│   └── settings.json
├── database/
│   └── pdfunlocker.db
├── profiles/
├── logs/
├── temp/
├── exports/
├── tests/
└── docs/
```

The live database, profile values, configuration, logs and temporary files stay inside the application directory.

Actual personal profile values must not be stored in public GitHub files.

## 2. PDF storage directory

The PDF storage directory is reserved for PDF files and user-requested PDF-related exports.

### Android — Termux

```text
/storage/emulated/0/PDFUnlocker/
```

This folder is alongside Android folders such as Download, Documents, DCIM, Movies and Pictures.

### Linux

```text
/home/fury/PDFUnlocker/
```

Here, `fury` represents the Linux username. The path must be generated using the detected user's home directory rather than hardcoded for other users.

### PDF storage structure

```text
PDFUnlocker/
├── Inbox/
├── Original/
├── Unlocked/
├── Locked/
├── Unsupported/
└── Export/
    ├── Profiles/
    └── Database/
```

Folder names and capitalization must be preserved.

## 3. PDF scan locations

During setup, the user selects folders to scan.

### Suggested Android folders

- Download
- Documents
- DCIM
- Pictures
- Movies

### Suggested Linux folders

- Downloads
- Documents
- Desktop
- Pictures
- Videos

Users can add custom folders and remove suggested folders.

### Recursive scanning rules

- Scan all subfolders recursively by default.
- Exclusions are optional and configurable.
- Automatically exclude the PDFUnlocker storage directory.
- Do not follow symbolic links by default.
- Detect duplicate PDFs using SHA-256.
- Do not modify, move or delete files in original scan locations.
- Keep the configured scan locations in application configuration.

## 4. PDF import and processing

Every discovered PDF is copied into:

```text
PDFUnlocker/Inbox/
```

The application processes the imported copy, never the source file.

An untouched archive copy is retained in:

```text
PDFUnlocker/Original/
```

The Original archive is retained whether unlocking succeeds or fails.

### Processing outcomes

| Result | Destination |
|---|---|
| Successfully unlocked | Unlocked/ |
| Still locked after all configured attempts | Locked/ |
| Corrupted or unsupported | Unsupported/ |

After processing, the Inbox working copy is moved to the appropriate destination.

The original scan-folder file remains untouched.

## 5. Retry behavior

The future command:

```bash
pdfunlocker retry --failed
```

Will retry PDFs from:

```text
PDFUnlocker/Locked/
```

The archived original and existing locked copy must be preserved until retry processing completes.

## 6. Export and backup

The PDF storage Export directory stores user-requested backups and exports.

```text
PDFUnlocker/Export/
├── Profiles/
└── Database/
```

Examples:

- Profile backups
- SQLite database exports

These are backup copies, not the live database or live profile storage.

## 7. Setup wizard

The primary setup command:

```bash
pdfunlocker setup
```

The following command must start the same setup process:

```bash
pdfunlocker install
```

### Setup sequence

1. Detect the operating system.
2. Set the default installation directory to `~/pdfunlocker`.
3. Set the default PDF storage directory:
   - Android: `/storage/emulated/0/PDFUnlocker`
   - Linux: `~/PDFUnlocker`
4. Verify storage access and permissions.
5. Create required application and PDF directories.
6. Ask the user to configure PDF scan folders.
7. Enable recursive scanning by default.
8. Allow optional scan exclusions.
9. Ask whether to create the first profile.
10. Collect and validate profile fields using the existing approved profile template.
11. Store actual profile values in the local SQLite database.
12. Verify the configuration and mark setup complete.

The user should be able to accept defaults or change paths when required.

On Termux, verify Android shared-storage permission before attempting to create or use the PDF storage directory.

## 8. Profile template

Use the existing approved Alpha v1 profile template:

```text
templates/profile/default_profile_template.yml
```

Do not add, remove or rename its 14 approved fields without a separately approved revision.

### Single-value fields

| Field ID | Field |
|---|---|
| 1001 | title |
| 1002 | first_name |
| 1003 | middle_name |
| 1004 | last_name |
| 1005 | birth_date |
| 1006 | pan |
| 1007 | pincode |

### Multiple-value fields

| Field ID | Field |
|---|---|
| 1008 | mobile |
| 1009 | email |
| 1020 | account_number |
| 1021 | customer_id |
| 1023 | crn |
| 1035 | vehicle_registration_number |
| 1036 | chassis_number |

Birth date is stored as DDMMYYYY.

Multiple-value fields use alphabetic suffixes as defined in the approved template.

The template defines fields and validation. Actual profile values are stored in SQLite.

## 9. Data integrity

- Never modify or delete original scan-folder files.
- Keep an untouched archive in Original/.
- Use SHA-256 for duplicate detection.
- Avoid repeated imports during subsequent scans.
- Keep file-processing records in SQLite.
- Record source path, file hash, import date and processing status.
- Keep profile values out of public rule files and ordinary logs.
- Keep backups separate from live application data.
- Avoid overwriting existing files when filenames collide.
- Preserve the original file extension.

## 10. Execution design decisions

- Use one unified execution engine.
- Do not use P1, P2 or P3 stages.
- Do not use manually assigned A1/B1/Z rule priority labels.
- Rule ordering is calculated automatically from database performance.
- Rule performance uses PDF-level success rate:
  successful PDFs divided by PDFs on which the rule was attempted.
- Untested rules go after tested rules.
- Profiles are processed one at a time in configured profile order.
- Stop immediately when a PDF is successfully unlocked.
- Maximum password attempt rate: 50 attempts per second.
- No unrestricted automatic brute-force search.
- Advanced mode remains a manual-only placeholder until separately implemented.

## 11. Future revisions

This document is the approved v1 baseline.

Future changes should be documented as v1.1, v1.2 or v2.0 as appropriate.

Existing approved requirements must not be changed silently.


---

## Revision notice

The approved path, persistent-data and export requirements have been superseded by **[PATH_DATA_EXPORT_REVISION_V1_2.md](PATH_DATA_EXPORT_REVISION_V1_2.md)**. The v1 document remains as a historical baseline; use v1.2 for current installation, data and export behavior.

---

## Revision notice — v1.3

The v1.3 path, installer and scan setup architecture supersedes earlier path
examples in this historical specification. See
[PATH_INSTALLER_SCAN_REVISION_V1_3.md](PATH_INSTALLER_SCAN_REVISION_V1_3.md)
for the canonical Android/Linux defaults, fixed private directory tree, public
Processed/Export layout, scan defaults, migration safeguards and profile-layer
boundary.
