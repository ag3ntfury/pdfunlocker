# Permanent profile field registry

The public `field_id` is permanent and separate from the internal SQLite
`field_number`. The internal number remains in place so existing foreign-key
relationships and profile value counters can be preserved.

| Field ID | Field key | Label | Multiplicity |
|---|---|---|---|
| `0100` | `TITLE` | Title | Single |
| `0200` | `FIRST_NAME` | First Name | Single |
| `0300` | `LAST_NAME` | Last Name | Single |
| `0400` | `MIDDLE_NAME` | Middle Name | Single |
| `0500` | `MOTHER_NAME` | Mother's Name | Single |
| `0600` | `DOB` | Date of Birth (`DDMMYYYY`) | Single |
| `0700` | `MOBILE` | Mobile Number | Multiple |
| `0800` | `EMAIL` | Email Address | Multiple |
| `0900` | `PINCODE` | Postal Code | Multiple |
| `1000` | `PAN` | PAN | Single |
| `1100` | `AADHAAR` | Aadhaar | Single; masked at rest |
| `1200A-F` | Bank 01 fields | See bank suffix table | A single; B-F multiple |
| `1201A-F` | Bank 02 fields | See bank suffix table | A single; B-F multiple |
| `...` | Further banks | Group increments by one through `1699` | A single; B-F multiple |
| `1700` | `INCORPORATION_DATE` | Incorporation Date (`DDMMYYYY`) | Single |
| `1800` | `TAN` | TAN | Multiple |
| `1900` | `GSTIN` | GSTIN | Multiple |
| `2000` | `EMPLOYEE_ID` | Employee ID | Multiple |
| `2100` | `UAN` | UAN | Multiple |
| `2200` | `PPO_NUMBER` | PPO Number | Multiple |
| `2300` | `PRAN` | PRAN | Multiple |
| `2400` | `POLICY_NUMBER` | Policy Number | Multiple |

## Bank group suffixes

| Suffix | Field key | Description |
|---|---|---|
| A | `BANK_{group}A` | Bank name (one per group) |
| B | `BANK_{group}B` | IFSC (multiple) |
| C | `BANK_{group}C` | CIF (multiple) |
| D | `BANK_{group}D` | Customer ID (multiple) |
| E | `BANK_{group}E` | Account number (multiple) |
| F | `BANK_{group}F` | Full card number (multiple; encrypted at rest) |

Card numbers are collected as complete 12-19 digit values and validated using
the Luhn checksum. They are encrypted with AES-256-GCM before being written to
SQLite or profile exports. The password-rule candidate resolver decrypts a card
only when a matching rule requests it. The key is stored separately at
`~/.pdfunlocker/config/card-number.key` with mode 0600, with a private recovery
copy at `~/.pdfunlocker/backups/keys/card-number.key`. Both key copies must be
included in protected backups. Without the matching key, encrypted card values
cannot be recovered. Aadhaar is validated using Verhoeff and masked before storage.

Legacy fields remain in the registry as archived definitions. Their internal
SQLite numbers and old three-digit aliases are not reused.
