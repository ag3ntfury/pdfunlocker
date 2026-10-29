# Installation Guide

PDF Unlocker is a command-line tool for processing password-protected PDFs that you own or are authorized to access.

## Requirements

- Python 3.11 or newer
- Git
- qpdf

## Ubuntu and Debian Linux

### 1. Install dependencies

    sudo apt update
    sudo apt install -y git python3 python3-venv python3-pip qpdf

### 2. Download the source code

    git clone https://github.com/ag3ntfury/pdfunlocker.git
    cd pdfunlocker

If you already cloned the repository, enter that existing directory instead.

### 3. Install

    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip setuptools wheel
    .venv/bin/python -m pip install -e .

### 4. Verify and initialize

    .venv/bin/pdfunlocker --help
    .venv/bin/pdfunlocker install

Follow the interactive prompts.

### 5. Run tests

    .venv/bin/python -m pip install pytest
    PYTHONPATH=src .venv/bin/python -m pytest -q

## Termux on Android

### 1. Install dependencies

    pkg update
    pkg install git python qpdf

### 2. Download and install

    git clone https://github.com/ag3ntfury/pdfunlocker.git
    cd pdfunlocker
    python -m venv .venv
    .venv/bin/python -m pip install --upgrade pip setuptools wheel
    .venv/bin/python -m pip install -e .

### 3. Verify and initialize

    .venv/bin/pdfunlocker --help
    .venv/bin/pdfunlocker install

## Updating an existing installation

Back up local configuration and review any uncommitted changes before updating.

    git pull --ff-only origin main
    .venv/bin/python -m pip install -e .

## Troubleshooting

- Python version errors: install Python 3.11 or newer.
- Command not found: use `.venv/bin/pdfunlocker`.
- PDF processing errors: verify that qpdf is installed.
- For other errors, open a GitHub issue with sensitive information removed.

## Privacy

Never publish personal profile files, passwords, private PDFs, account information, databases, or sensitive logs.

Use PDF Unlocker only on documents you own or are authorized to access.
