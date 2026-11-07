import os
import subprocess
import sys
from pathlib import Path


def test_parallel_processes_create_one_consistent_key(tmp_path):
    app_dir = tmp_path / "app"
    key_path = app_dir / "config" / "card-number.key"

    worker = """
import sys
from pathlib import Path
from pdfunlocker.profiles import card_crypto

app_dir = Path(sys.argv[1])
key_path = Path(sys.argv[2])
card_number = sys.argv[3]

card_crypto.APP_DIR = app_dir
card_crypto.KEY_PATH = key_path

encrypted = card_crypto.encrypt_card_number(card_number)
decrypted = card_crypto.decrypt_card_number(encrypted)

assert decrypted == card_number
"""

    numbers = [
        f"{4000000000000000 + index:016d}"
        for index in range(16)
    ]

    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker,
                str(app_dir),
                str(key_path),
                number,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=os.environ.copy(),
        )
        for number in numbers
    ]

    failures = []

    for index, process in enumerate(processes):
        stdout, stderr = process.communicate(timeout=60)

        if process.returncode != 0:
            failures.append(
                f"Worker {index}: exit={process.returncode}\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )

    assert not failures, "\n\n".join(failures)

    recovery_path = app_dir / "backups" / "keys" / "card-number.key"

    assert key_path.is_file()
    assert recovery_path.is_file()
    assert len(key_path.read_bytes()) == 32
    assert key_path.read_bytes() == recovery_path.read_bytes()

    assert key_path.stat().st_mode & 0o777 == 0o600
    assert recovery_path.stat().st_mode & 0o777 == 0o600
