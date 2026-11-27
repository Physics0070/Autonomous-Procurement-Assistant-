"""Storage abstraction.

Files never go into the quotation documents. Only an opaque `storage_key` is persisted (GridFS keeps the bytes in
separate chunk collections),
so the backend can move to S3 / R2 / MinIO by adding one more implementation.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional


@dataclass
class StoredFile:
    key: str
    size_bytes: int
    content_type: Optional[str] = None
    backend: str = "local"


class StorageBackend(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    async def save(self, data: bytes, *, filename: str, prefix: str = "", content_type: Optional[str] = None) -> StoredFile:
        ...

    @abc.abstractmethod
    async def load(self, key: str) -> bytes:
        ...

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        ...

    @abc.abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abc.abstractmethod
    def local_path(self, key: str) -> Optional[str]:
        """Filesystem path if the backend has one, else None."""
