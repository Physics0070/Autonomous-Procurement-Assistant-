"""MongoDB GridFS storage: originals survive a redeploy on hosts whose disk is wiped (Render's free tier), with no
extra service, because the app already has MongoDB. Keys have the same shape as local keys (organization prefix)."""
from __future__ import annotations

import uuid
from typing import Optional

from gridfs.errors import NoFile
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from app.core.database import get_database
from app.core.errors import NotFoundError
from app.services.storage.base import StorageBackend, StoredFile
from app.services.storage.local import _safe_name


class GridFSStorageBackend(StorageBackend):
    name = "gridfs"

    def _bucket(self) -> AsyncIOMotorGridFSBucket:
        return AsyncIOMotorGridFSBucket(get_database(), bucket_name="originals")

    async def save(self, data: bytes, *, filename: str, prefix: str = "", content_type: Optional[str] = None) -> StoredFile:
        key = "/".join(p for p in [prefix.strip("/"), f"{uuid.uuid4().hex}_{_safe_name(filename)}"] if p)
        await self._bucket().upload_from_stream(key, data, metadata={"content_type": content_type})
        return StoredFile(key=key, size_bytes=len(data), content_type=content_type, backend=self.name)

    async def load(self, key: str) -> bytes:
        try:
            stream = await self._bucket().open_download_stream_by_name(key)
        except NoFile:
            raise NotFoundError(f"Stored file not found: {key}") from None
        return await stream.read()

    async def delete(self, key: str) -> bool:
        bucket, deleted = self._bucket(), False
        async for row in bucket.find({"filename": key}):
            await bucket.delete(row._id)
            deleted = True
        return deleted

    def exists(self, key: str) -> bool:  # only knowable asynchronously; callers use load() and catch NotFoundError
        return True

    def local_path(self, key: str) -> Optional[str]:
        return None
