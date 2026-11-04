PDF Unlocker — Permanent Field Registry Interaction and Card Security Fixes

This package is an update to the permanent field registry implementation that
is already installed. It is NOT a fresh field-registry migration.

IMPORTANT:
- Do NOT run tools/apply_field_registry.py again. The prior migration already
  created profile ID 2 and deleted profile ID 1 after its earlier verification.
  Running that replacement workflow again could create another profile and
  replace the current one.
- This update preserves the current active profile (currently ID 2).
- After installing and testing this patch, run:
    PYTHONPATH="$PWD/src:$PWD" python tools/secure_existing_card_values.py
  That tool backs up the active profile database, profile exports, rules,
  configuration, and card encryption key before encrypting any existing full
  card numbers. It does not create, replace, or delete profiles.
- The PDF-processing database is never opened by that tool.

Changes:
1. Invalid-value retry now accepts a corrected value directly. Empty Enter
   skips; a non-empty correction is validated immediately and repeated until
   valid or skipped.
2. Bank card field 1200F accepts the full 12-19 digit number, validates Luhn,
   and encrypts it with AES-256-GCM before SQLite/profile-export persistence.
3. The rule candidate resolver decrypts card values only when a matching card
   field/rule is requested.
4. The key is stored separately at ~/.pdfunlocker/config/card-number.key with
   mode 0600. A private recovery copy is maintained at
   ~/.pdfunlocker/backups/keys/card-number.key. Both must be protected and
   included in backups. Losing the key makes encrypted card values unrecoverable.
5. Indian PIN codes default to six digits. International values must be
   explicit, for example US:90210 or GB:SW1A 1AA.
6. Profile collection and display follow permanent field-ID order.
7. Acronyms retain their proper capitalization (UAN, PRAN, PPO, GSTIN, TAN,
   IFSC, CIF, PAN, ID).
8. The profile-replacement verification now checks every saved value, encrypted
   card round trips, export equality, foreign keys, and repeatable counters.

Dependencies:
- phonenumbers (already required by this project)
- cryptography >= 42.0.0 (new)

Run the complete Termux test suite after installation using the real installed
phonenumbers package. The package tests also include card encryption and rule
resolver checks.
