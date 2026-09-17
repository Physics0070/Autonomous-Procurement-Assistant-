"""Repository base.

Everything MongoDB-specific lives in this layer. Services and routes above it
only ever see plain dicts keyed by string ids, so the storage engine can be
replaced (PostgreSQL, etc.) by rewriting these classes alone.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from bson import ObjectId
from bson.errors import InvalidId
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.core.errors import NotFoundError, ValidationError


def to_object_id(value: Any, field: str = "id") -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError) as exc:
        raise ValidationError(f"Invalid {field}: {value!r}") from exc


def maybe_object_id(value: Any) -> Optional[ObjectId]:
    if value in (None, "", "null"):
        return None
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def serialize(doc: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Convert a Mongo document into a plain, API-safe dict.

    Raw Mongo documents never leave the repository layer.
    """
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            out["id"] = str(value)
        elif isinstance(value, ObjectId):
            out[key] = str(value)
        elif isinstance(value, list):
            out[key] = [serialize(v) if isinstance(v, dict) else (str(v) if isinstance(v, ObjectId) else v) for v in value]
        elif isinstance(value, dict):
            out[key] = serialize(value)
        else:
            out[key] = value
    return out


class BaseRepository:
    collection_name: str = ""

    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    @property
    def collection(self) -> AsyncIOMotorCollection:
        return self.db[self.collection_name]


class OrgScopedRepository(BaseRepository):
    """Repository for collections partitioned by organization.

    Every query built here is forced through _scope(), which makes it
    structurally impossible to read another organization's rows.
    """

    def _scope(self, organization_id: str, extra: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        query: dict[str, Any] = {"organization_id": to_object_id(organization_id, "organization_id")}
        if extra:
            query.update(extra)
        return query

    async def get(self, organization_id: str, entity_id: str) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(
            self._scope(organization_id, {"_id": to_object_id(entity_id)})
        )
        return serialize(doc)

    async def get_or_404(self, organization_id: str, entity_id: str) -> dict[str, Any]:
        doc = await self.get(organization_id, entity_id)
        if doc is None:
            raise NotFoundError(f"{self.collection_name[:-1].capitalize()} not found")
        return doc

    async def list(
        self,
        organization_id: str,
        filters: Optional[dict[str, Any]] = None,
        sort: Optional[Sequence[tuple[str, int]]] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cursor = self.collection.find(self._scope(organization_id, filters))
        cursor = cursor.sort(list(sort) if sort else [("created_at", -1)])
        cursor = cursor.skip(max(skip, 0)).limit(max(min(limit, 500), 1))
        return [serialize(d) for d in await cursor.to_list(length=limit)]

    async def count(self, organization_id: str, filters: Optional[dict[str, Any]] = None) -> int:
        return await self.collection.count_documents(self._scope(organization_id, filters))

    async def create(self, organization_id: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = dict(data)
        payload["organization_id"] = to_object_id(organization_id, "organization_id")
        payload.setdefault("created_at", utcnow())
        payload["updated_at"] = utcnow()
        result = await self.collection.insert_one(payload)
        payload["_id"] = result.inserted_id
        return serialize(payload)  # type: ignore[return-value]

    async def update(
        self, organization_id: str, entity_id: str, data: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        payload = {k: v for k, v in data.items() if v is not None or k.endswith("_id")}
        if not payload:
            return await self.get(organization_id, entity_id)
        payload["updated_at"] = utcnow()
        doc = await self.collection.find_one_and_update(
            self._scope(organization_id, {"_id": to_object_id(entity_id)}),
            {"$set": payload},
            return_document=True,
        )
        return serialize(doc)

    async def raw_update(
        self, organization_id: str, entity_id: str, update: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Apply a raw update document (for $set/$push combinations)."""
        update.setdefault("$set", {})["updated_at"] = utcnow()
        doc = await self.collection.find_one_and_update(
            self._scope(organization_id, {"_id": to_object_id(entity_id)}),
            update,
            return_document=True,
        )
        return serialize(doc)

    async def delete(self, organization_id: str, entity_id: str) -> bool:
        result = await self.collection.delete_one(
            self._scope(organization_id, {"_id": to_object_id(entity_id)})
        )
        return result.deleted_count > 0
