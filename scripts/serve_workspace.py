"""Launch the local workspace without exposing operator access to the network."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "evidencetrace-v0.2.db")
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit("Build the source library first: python scripts/build_corpus.py")
    os.environ["EVIDENCETRACE_DB_PATH"] = str(args.db.resolve())
    os.environ["EVIDENCETRACE_LOCAL_MODE"] = "true"
    sys.path.insert(0, str(ROOT))
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=args.port)
