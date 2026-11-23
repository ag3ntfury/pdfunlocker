# PDF Unlocker v1.3.3 — Manual installation repair

## Scope

- Isolate manual installer tests from the user's live installation.
- Resolve database migration candidates deterministically: an existing active canonical database takes precedence over a retained legacy database when creating a separate installation.
- Re-running setup in the current installation recognizes its existing canonical database without treating the retained legacy copy as a migration conflict.
- If a destination already has a database while another distinct candidate exists, stop without overwriting either database.
- If no canonical source exists and multiple legacy candidates exist, stop without guessing.
- Preserve all source databases; migration uses SQLite's online backup API and integrity checks.

## Test coverage

Manual installation tests cover Linux and Android custom paths, scan selection, path validation, existing settings backup/preservation, cancellation, and database migration safety. Test setup uses a temporary fake source checkout and never inspects or modifies the developer's real home installation.

## Validation

- Full pytest suite: 252 passed, 362 subtests passed.
- Python compileall: passed.
- CLI version and help: passed.

No source PDFs are modified. No profile schema or profile records are intentionally changed. No Git commit or push is performed.
