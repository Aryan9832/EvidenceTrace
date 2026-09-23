"""Build a Linux-compatible AWS Lambda deployment archive."""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = ROOT / "build"
PACKAGE_ROOT = BUILD_ROOT / "lambda"
ARCHIVE_PATH = BUILD_ROOT / "evidencetrace-lambda.zip"


def main() -> None:
    if PACKAGE_ROOT.exists():
        shutil.rmtree(PACKAGE_ROOT)
    PACKAGE_ROOT.mkdir(parents=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--target",
            str(PACKAGE_ROOT),
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "312",
            "--only-binary=:all:",
            "-r",
            str(ROOT / "requirements-lambda.txt"),
        ],
        check=True,
    )
    shutil.copytree(ROOT / "app", PACKAGE_ROOT / "app")
    (PACKAGE_ROOT / "data").mkdir()
    shutil.copy2(ROOT / "data" / "evidencetrace.db", PACKAGE_ROOT / "data" / "evidencetrace.db")
    (PACKAGE_ROOT / "evals").mkdir()
    shutil.copy2(ROOT / "evals" / "demo_golden_set.json", PACKAGE_ROOT / "evals" / "demo_golden_set.json")

    if ARCHIVE_PATH.exists():
        ARCHIVE_PATH.unlink()
    with zipfile.ZipFile(ARCHIVE_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in PACKAGE_ROOT.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(PACKAGE_ROOT))
    print(f"Built {ARCHIVE_PATH} ({ARCHIVE_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
