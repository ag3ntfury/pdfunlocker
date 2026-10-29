# Contributing to PDF Unlocker

Contributions are welcome, including bug fixes, tests, documentation improvements, and rule examples using synthetic data.

## Workflow

1. Fork https://github.com/ag3ntfury/pdfunlocker on GitHub.
2. Clone your fork, replacing YOUR_GITHUB_USERNAME with your GitHub username:

       git clone https://github.com/YOUR_GITHUB_USERNAME/pdfunlocker.git
       cd pdfunlocker

3. Add the original repository:

       git remote add upstream https://github.com/ag3ntfury/pdfunlocker.git

4. Create a branch:

       git switch -c docs/your-change

5. Set up the project using docs/installation.md.
6. Run the tests:

       PYTHONPATH=src .venv/bin/python -m pytest -q

7. Review your changes:

       git diff --check
       git status --short

8. Stage only the files you intend to contribute, then commit and push:

       git add path/to/changed-file
       git commit -m "Describe your change"
       git push -u origin docs/your-change

9. Open a pull request on GitHub against ag3ntfury/pdfunlocker main.

Replace the example file path and branch name with your actual changes.

## Bug reports

Include steps to reproduce the problem, expected and actual behavior, your operating system, Python version, and sanitized error output.

## Privacy and security

Never contribute real PDFs, passwords, profile exports, personal account data, private databases, or sensitive logs. Use synthetic examples for tests and rule contributions. Keep local profile files private.

For major changes, open an issue to discuss the proposed approach first.
