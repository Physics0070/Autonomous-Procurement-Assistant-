from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.errors import NotFoundError
from app.services.storage.base import StorageBackend, StoredFile

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(filename: str) -> str:
    base = os.path.basename(filename or "file")
    base = _SAFE.sub("_", base).strip("._") or "file"
    return base[:120]


class LocalStorageBackend(StorageBackend):
    """Filesystem-backed storage rooted at STORAGE_LOCAL_PATH."""

    name = "local"

    def __init__(self, root: Optional[str] = None):
        base = Path(root or settings.STORAGE_LOCAL_PATH)
        if not base.is_absolute():
            base = (Path(__file__).resolve().parents[3] / base).resolve()
        self.root = base
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        # Prevent traversal outside the storage root.
        target = (self.root / key).resolve()
        if not str(target).startswith(str(self.root)):
            raise NotFoundError("Invalid storage key")
        return target

    async def save(
        self, data: bytes, *, filename: str, prefix: str = "", content_type: Optional[str] = None
    ) -> StoredFile:
        safe = _safe_name(filename)
        key = "/".join(p for p in [prefix.strip("/"), f"{uuid.uuid4().hex}_{safe}"] if p)
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> None:
            path.write_bytes(data)

        await asyncio.to_thread(_write)
        return StoredFile(key=key, size_bytes=len(data), content_type=content_type, backend=self.name)

    async def load(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.exists():
            raise NotFoundError(f"Stored file not found: {key}")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> bool:
        path = self._resolve(key)
        if path.exists():
            await asyncio.to_thread(path.unlink)
            return True
        return False

    def exists(self, key: str) -> bool:
        try:
            return self._resolve(key).exists()
        except NotFoundError:
            return False

    def local_path(self, key: str) -> Optional[str]:
        try:
            return str(self._resolve(key))
        except NotFoundError:
            return None


_backend: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """Factory. Add S3/MinIO here without touching any caller."""
    global _backend
    if _backend is None:
        if settings.STORAGE_BACKEND == "local":
            _backend = LocalStorageBackend()
        elif settings.STORAGE_BACKEND == "gridfs":
            from app.services.storage.gridfs import GridFSStorageBackend

            _backend = GridFSStorageBackend()
        else:
            # Unknown backends fall back to local rather than failing the app.
            _backend = LocalStorageBackend()
    return _backend
