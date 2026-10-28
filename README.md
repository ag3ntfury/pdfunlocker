# PDF Unlocker

**Version:** `0.1.0-alpha.1` — early testing only.

PDF Unlocker is a CLI-first utility for processing password-protected PDF files that you own or are explicitly authorized to access. It generates candidate passwords from locally configured profile fields and records processing history.

The project is under active development. Commands, configuration formats, and behavior may change. Do not rely on this alpha version as the only copy of important documents, and do not use it to access documents without permission.

## Current goals

- Process authorized password-protected PDFs.
- Generate controlled candidate-password patterns from local profile information.
- Support multiple profiles and account fields.
- Prioritize candidate patterns using rule priorities.
- Record processing history in SQLite.
- Detect duplicate PDFs using SHA-256.
- Avoid printing candidate passwords in normal logs.
- Support Termux/Android and Linux.

## Requirements

- Python 3.11 or newer
- PyYAML 6 or newer
- pytest for running the test suite

## Install from a source checkout

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
pdfunlocker --help
```

On Termux, use the Python environment and activation commands appropriate to your Termux setup.

## Tests

```sh
python -m pip install pytest
PYTHONPATH=src python -m pytest -q
```

## Local data and privacy

Profile files can contain highly sensitive personal information. Keep them on your device, do not commit them, and use synthetic values in tests and bug reports. Review `.gitignore` before creating a commit. Do not place real PDFs, passwords, profile exports, databases, or logs in public issues.

## Rules

Rules define candidate-password patterns from profile fields. The default case transformations offered by the current rule workflow are `capitalize`, `upper`, and `lower`. Rules with priority `Z` are unapproved and are not attempted. See [Rules documentation](docs/rules.md).

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE).
