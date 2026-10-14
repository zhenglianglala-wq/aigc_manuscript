"""Back up or restore local SQLite data. Credentials are never copied."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def validate(path: Path) -> None:
    with sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("Unsupported database version")
        rows = db.execute("SELECT kind,id,project_id,value FROM entities").fetchall()
        entities = {(kind, identifier): json.loads(value) for kind, identifier, _, value in rows}
        if ("profile", "owner") not in entities:
            raise ValueError("Backup has no local profile")
        for kind, identifier, project_id, value in rows:
            record = entities[kind, identifier]
            if str(record.get("id")) != identifier:
                raise ValueError(f"Mismatched entity id: {kind}")
            if project_id and ("project", project_id) not in entities:
                raise ValueError(f"Dangling project reference: {kind}")
            photo_id = record.get("photo_project_id")
            if photo_id and ("photo_project", photo_id) not in entities:
                raise ValueError(f"Dangling photo project reference: {kind}")
            if kind == "message" and ("conversation", record["conversation_id"]) not in entities:
                raise ValueError("Dangling conversation reference")
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Backup reference integrity check failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "validate", "restore"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--confirm", action="store_true", help="Explicitly replace local data; stop server first")
    args = parser.parse_args()
    db_path = args.data_dir.resolve() / "studio.sqlite3"
    if args.action == "validate":
        validate(args.file)
        print("Backup schema and integrity are valid.")
        return
    if args.action == "backup":
        if not db_path.is_file():
            raise SystemExit("Database not found. Start the application first.")
        if args.file.exists():
            raise SystemExit("Backup destination exists; choose a new filename.")
        args.file.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as source:
            with sqlite3.connect(args.file) as target:
                source.backup(target)
        validate(args.file)
        print(f"Backup saved: {args.file.resolve()} (contains project and chat data)")
        return
    validate(args.file)
    if not args.confirm:
        raise SystemExit("Backup validated. Stop the server and repeat with --confirm to replace local data.")
    args.data_dir.mkdir(parents=True, exist_ok=True)
    # Acquire an exclusive write lock: refuse when another process owns a write lock.
    for suffix in ("-wal", "-shm"):
        if Path(str(db_path) + suffix).exists():
            raise SystemExit("Database has WAL files. Stop the server before restoring.")
    existing = sqlite3.connect(db_path, timeout=0.1)
    try:
        existing.execute("BEGIN EXCLUSIVE")
    finally:
        existing.rollback()
        existing.close()
    fd, name = tempfile.mkstemp(prefix="restore-", suffix=".sqlite3", dir=args.data_dir)
    os.close(fd)
    staged = Path(name)
    try:
        with sqlite3.connect(f"{args.file.resolve().as_uri()}?mode=ro", uri=True) as source:
            with sqlite3.connect(staged) as target:
                source.backup(target)
        validate(staged)
        if db_path.exists():
            preserved = db_path.with_name("studio.pre-restore.sqlite3")
            if preserved.exists():
                raise SystemExit("Previous pre-restore backup exists. Move it before restoring again.")
            with sqlite3.connect(db_path) as source:
                with sqlite3.connect(preserved) as target:
                    source.backup(target)
        os.replace(staged, db_path)
    finally:
        staged.unlink(missing_ok=True)
    print("Restored. Previous data retained in studio.pre-restore.sqlite3; backup may restore old memories.")


if __name__ == "__main__":
    main()
