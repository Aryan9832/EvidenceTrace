"""Build a Lambda archive with public corpus data, never private reviews/traces."""
from __future__ import annotations
import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.database import Database


def public_database(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ValueError("Export destination must be new")
    target = Database(destination)
    original = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    original.row_factory = sqlite3.Row
    try:
        with target.connection() as conn:
            for table in ("documents", "chunks"):
                columns = [r["name"] for r in original.execute(f"PRAGMA table_info({table})")]
                allowed = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                columns = [c for c in columns if c in allowed]
                names = ','.join(columns)
                rows = original.execute(f"SELECT {names} FROM {table}").fetchall()
                conn.executemany(f"INSERT INTO {table} ({names}) VALUES ({','.join('?' for _ in columns)})", [tuple(r) for r in rows])
            conn.execute("""INSERT INTO chunks_fts(rowid,text,title,source_uri)
                            SELECT c.id,c.text,d.title,d.source_uri FROM chunks c JOIN documents d ON d.id=c.document_id""")
    finally:
        original.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "evidencetrace-v0.2.db")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "evidencetrace-v0.2-lambda.zip")
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit("Build the corpus first: python scripts/build_corpus.py")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="evidencetrace-release-") as temporary:
        staging = Path(temporary)
        subprocess.run([sys.executable,"-m","pip","install","--target",str(staging),
                        "--platform","manylinux2014_x86_64","--implementation","cp","--python-version","312",
                        "--only-binary=:all:","-r",str(ROOT / "requirements-lambda.txt")],check=True)
        shutil.copytree(ROOT / "app", staging / "app", ignore=shutil.ignore_patterns("__pycache__"))
        (staging / "data").mkdir()
        public_database(args.db, staging / "data" / "evidencetrace.db")
        shutil.copytree(ROOT / "data" / "demo", staging / "data" / "demo")
        shutil.copytree(ROOT / "evals", staging / "evals")
        info = {"version":"0.2.0","snapshot":Database(staging / "data" / "evidencetrace.db").snapshot(),
                "private_records_included":False,"storage":"Lambda /tmp is ephemeral; public research preview only"}
        (staging / "release.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        with zipfile.ZipFile(args.output,"w",zipfile.ZIP_DEFLATED) as archive:
            for path in staging.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path,path.relative_to(staging))
    print(f"Built {args.output} ({args.output.stat().st_size:,} bytes); no private records included.")


if __name__ == "__main__":
    main()
