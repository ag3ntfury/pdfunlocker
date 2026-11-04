PDF Unlocker — Permanent Field Registry Implementation

This package adds public permanent field IDs while retaining the internal
SQLite field_number as a compatibility key. It updates profile collection,
validation, rule parsing/candidate resolution, and existing YAML rules.

Registry:
  0100 TITLE
  0200 FIRST_NAME
  0300 LAST_NAME
  0400 MIDDLE_NAME
  0500 MOTHER_NAME
  0600 DOB
  0700 MOBILE
  0800 EMAIL
  0900 PINCODE
  1000 PAN
  1100 AADHAAR
  1200A-F Bank 01
  1201A-F Bank 02 (allocated when added)
  ... through bank group 1699
  1700 INCORPORATION_DATE
  1800 TAN
  1900 GSTIN
  2000 EMPLOYEE_ID
  2100 UAN
  2200 PPO_NUMBER
  2300 PRAN
  2400 POLICY_NUMBER

Bank suffixes:
  A Bank Name (single)
  B IFSC (multiple)
  C CIF (multiple)
  D Customer ID (multiple)
  E Account Number (multiple)
  F Card Number (multiple)

Security note:
  Aadhaar is validated with Verhoeff and stored masked.
  Full 12-19 digit card numbers are validated with Luhn and encrypted with
  AES-256-GCM before persistence in SQLite and profile exports. The key is
  stored separately at ~/.pdfunlocker/config/card-number.key with mode 0600.
  The password-rule candidate resolver decrypts a card only when a rule asks
  for that field. Keep protected backups of the key with database backups.

Migration behavior:
  - Adds field_definitions.field_id and a unique index.
  - Preserves field_number and value_counters foreign keys.
  - Preserves existing profile values during registry migration.
  - Archives superseded split/global bank fields.
  - Migrates active YAML rule IDs and archives the pre-migration rule files.
  - Optionally creates a new profile first, then deletes the configured old
    profile only after the new profile has been saved and verified.
  - Does not open or modify the PDF-processing database.

Installation command is provided in the ChatGPT response. Keep the existing
PreRegistry backup in Android Download until the new profile is verified.

Testing note:
  The source package was compiled and the project test suite passed 290 tests
  and 9 subtests using a temporary test-only phonenumbers shim because the
  packaging environment did not have the project's phonenumbers dependency.
  Run the test suite in Termux with the actual declared phonenumbers dependency
  before accepting the migration.
