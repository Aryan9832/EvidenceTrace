"""Compatibility entry point for the expanded manifest-driven source builder."""
import runpy
import sys
from pathlib import Path

if __name__ == "__main__":
    if "--ingest" in sys.argv:
        sys.argv.remove("--ingest")
    print("The corpus builder now covers NIST and OWASP; use scripts/build_corpus.py.")
    runpy.run_path(str(Path(__file__).with_name("build_corpus.py")), run_name="__main__")
