# Profile database backups

PDF Unlocker profile backups are separate from the PDF-processing database backups. They contain the authoritative `profiles.sqlite3` database and, when present, the matching card-number encryption key. Legacy `.env` profile files are exports and are not included as authoritative data.

## Commands

```text
pdfunlocker profile backup [--output /path/to/name.pupb]
pdfunlocker profile backups [--directory /path/to/backup-directory]
pdfunlocker profile restore /path/to/name.pupb
```

`backup` asks for a new passphrase twice. Passphrases must contain at least 12 characters. `backups` lists `.pupb` files in the private default directory (`~/.pdfunlocker/backups/profiles`) unless a directory is supplied. `restore` asks for confirmation and the backup passphrase. It creates an encrypted safety backup of the current profile database before replacement.

## Security and operational notes

- The package uses Scrypt (N=32768, r=8, p=1) to derive an AES-256-GCM key. Data is encrypted in authenticated 1 MiB chunks; an authenticated final marker detects truncation.
- The package contains personal profile data and the card-number key. Store it as sensitive material even though it is encrypted.
- Keep the passphrase separately from the backup file. There is no passphrase recovery mechanism.
- Do not run backup or restore while another PDF Unlocker process can write profile data. Close all other PDF Unlocker processes first. The CLI warns before restore; it cannot reliably detect every external process.
- Restore validates the encrypted package, manifest hashes, SQLite integrity, foreign keys, schema version, and every encrypted card value before replacing active files. It also creates a safety backup and attempts an in-process rollback if replacement fails.
- The database and separate key files cannot be replaced as one filesystem-atomic transaction. The safety backup and rollback reduce risk but do not replace an independent backup strategy.
- Restored SQLite data is authoritative. Legacy profile `.env` exports are not part of the package and can be regenerated when profiles are loaded through the existing manager.
- The backup feature currently accepts profile schema version 4. Run the application normally to complete supported migrations before creating a backup.
- These commands do not modify the existing PDF-processing database backup workflow.


## Verify an encrypted backup without restoring it

Use `verify` to authenticate and validate a `.pupb` file without replacing or
modifying the active profile database or card-encryption keys:

```text
pdfunlocker profile verify /path/to/profiles-backup.pupb
```

The command prompts for the backup passphrase. It decrypts into a private
temporary directory, checks authenticated encryption, archive checksums,
SQLite integrity and foreign keys, schema compatibility, profile/value counts,
and encrypted card values against the bundled card key. Temporary plaintext
is removed when verification ends. Verification is not a restore test against
the live installation; it does not change active profile files.


- Backup manifest JSON is limited to 64 KiB and is read through a bounded
  stream, preventing an oversized manifest from being loaded into memory.
- Restored and rollback profile database files are required to have mode
  `0600`. If restrictive permissions cannot be enforced, the restore fails
  rather than continuing with a potentially exposed database file.
