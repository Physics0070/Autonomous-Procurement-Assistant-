"""Back up and restore the MongoDB database, including the original quotation files kept in GridFS.

    python scripts/backup_db.py backup                      # -> ../backups/<db>-<UTC time>/
    python scripts/backup_db.py restore <folder> --into <empty database name>
    python scripts/backup_db.py verify <folder> --against <database name>

One gzip file of BSON documents per collection plus its index definitions: the same content `mongodump` writes, without
needing the MongoDB tools installed. A restore only goes into an EMPTY database, so it can never overwrite live data;
switch the app to the restored database with MONGODB_DB_NAME once it has been checked.

Schedule `backup` daily (Windows Task Scheduler, cron, or a Render cron job) and copy the folder off the machine; keep
at least 7 daily copies. A MongoDB Atlas free (M0) cluster has no automatic backups, so this script is the backup there.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import bson
from pymongo import MongoClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "backups"


def _db(name: str):
    return MongoClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)[name]


def backup(out_root: Path = DEFAULT_DIR, db_name: str | None = None) -> Path:
    db = _db(db_name or settings.MONGODB_DB_NAME)
    folder = out_root / f"{db.name}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    folder.mkdir(parents=True)
    manifest = {"database": db.name, "created_at": datetime.now(timezone.utc).isoformat(), "collections": {}}
    for name in sorted(db.list_collection_names()):
        digest, count = hashlib.sha256(), 0
        with gzip.open(folder / f"{name}.bson.gz", "wb") as out:
            for doc in db[name].find().sort("_id", 1):
                raw = bson.encode(doc)
                out.write(raw)
                digest.update(raw)
                count += 1
        indexes = [{"key": list(ix["key"].items()), **{k: v for k, v in ix.items() if k not in ("key", "v", "ns")}}
                   for ix in db[name].list_indexes() if ix["name"] != "_id_"]
        manifest["collections"][name] = {"documents": count, "sha256": digest.hexdigest(), "indexes": indexes}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str), encoding="utf-8")
    return folder


def restore(folder: Path, into: str) -> dict:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    db = _db(into)
    if db.list_collection_names():
        raise SystemExit(f"Refusing to restore into '{into}': it is not empty. Choose a new database name.")
    for name, meta in manifest["collections"].items():
        with gzip.open(folder / f"{name}.bson.gz", "rb") as src:
            docs = bson.decode_all(src.read())
        if docs:
            db[name].insert_many(docs, ordered=True)
        else:
            db.create_collection(name)
        for ix in meta["indexes"]:
            options = {k: v for k, v in ix.items() if k != "key"}
            db[name].create_index([tuple(pair) for pair in ix["key"]], **options)
    return verify(folder, into)


def verify(folder: Path, against: str) -> dict:
    """Document count and content hash of every collection, compared with the backup's manifest."""
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    db = _db(against)
    report = {}
    for name, meta in manifest["collections"].items():
        digest = hashlib.sha256()
        count = 0
        for doc in db[name].find().sort("_id", 1):
            digest.update(bson.encode(doc))
            count += 1
        report[name] = count == meta["documents"] and digest.hexdigest() == meta["sha256"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--out", type=Path, default=DEFAULT_DIR)
    r = sub.add_parser("restore")
    r.add_argument("folder", type=Path)
    r.add_argument("--into", required=True)
    v = sub.add_parser("verify")
    v.add_argument("folder", type=Path)
    v.add_argument("--against", required=True)
    args = parser.parse_args()

    if args.command == "backup":
        print(backup(args.out))
        return 0
    report = restore(args.folder, args.into) if args.command == "restore" else verify(args.folder, args.against)
    bad = [name for name, ok in report.items() if not ok]
    print(f"{len(report) - len(bad)} of {len(report)} collections identical" + (f"; differ: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
