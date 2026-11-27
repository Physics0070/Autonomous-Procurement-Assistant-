"""A backup restores byte-for-byte, including original files kept in GridFS, and never over live data."""
import uuid

import pytest

API = "/api/v1"


async def test_backup_and_restore_round_trip_including_gridfs(api, db, org_a, tmp_path):
    from pymongo import MongoClient

    from app.api.deps import storage
    from app.core.config import settings
    from app.main import app
    from app.services.storage.gridfs import GridFSStorageBackend
    from scripts.backup_db import backup, restore

    app.dependency_overrides[storage] = lambda: GridFSStorageBackend()
    original = b"item,qty,rate\nMarker,10,25\n"
    up = await api.post(f"{API}/documents/upload", headers=org_a["headers"], files={"file": ("quote.csv", original, "text/csv")})
    assert up.status_code == 201

    folder = backup(tmp_path, db_name=db.name)
    target = f"restore_test_{uuid.uuid4().hex[:8]}"
    client = MongoClient(settings.MONGODB_URI)
    try:
        report = restore(folder, target)
        assert report and all(report.values()), report
        assert "originals.files" in report and "originals.chunks" in report
        restored = client[target]
        chunks = restored["originals.chunks"].find({"files_id": restored["originals.files"].find_one()["_id"]}).sort("n", 1)
        assert b"".join(c["data"] for c in chunks) == original  # the uploaded file itself came back
        with pytest.raises(SystemExit, match="not empty"):
            restore(folder, target)  # a second restore would overwrite: refused
    finally:
        client.drop_database(target)
