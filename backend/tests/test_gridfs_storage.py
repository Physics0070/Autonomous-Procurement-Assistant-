"""Originals kept in MongoDB GridFS: saved, served back unchanged, scoped by organization, deletable."""
import pytest

API = "/api/v1"


async def test_gridfs_round_trip_and_delete(db):
    from app.core.errors import NotFoundError
    from app.services.storage.gridfs import GridFSStorageBackend

    store = GridFSStorageBackend()
    saved = await store.save(b"%PDF-1.4 hello", filename='../evil "q".pdf', prefix="org1")
    assert saved.key.startswith("org1/") and ".." not in saved.key and saved.backend == "gridfs"
    assert await store.load(saved.key) == b"%PDF-1.4 hello"
    assert await store.delete(saved.key)
    with pytest.raises(NotFoundError):
        await store.load(saved.key)


async def test_an_upload_is_served_back_from_gridfs_and_not_to_another_org(api, db, org_a, org_b):
    from app.api.deps import storage
    from app.main import app
    from app.services.storage.gridfs import GridFSStorageBackend

    app.dependency_overrides[storage] = lambda: GridFSStorageBackend()
    body = b"item,qty,rate\nMarker,10,25\n"
    up = await api.post(f"{API}/documents/upload", headers=org_a["headers"], files={"file": ("quote.csv", body, "text/csv")})
    assert up.status_code == 201, up.text
    qid = up.json()["quotation_id"]
    mine = await api.get(f"{API}/quotations/{qid}/file", headers=org_a["headers"])
    assert mine.status_code == 200 and mine.content == body and "quote.csv" in mine.headers["content-disposition"]
    theirs = await api.get(f"{API}/quotations/{qid}/file", headers=org_b["headers"])
    assert theirs.status_code == 404
