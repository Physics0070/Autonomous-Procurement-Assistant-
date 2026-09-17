"""Channel connections (Gmail today). One per organization and provider."""
from __future__ import annotations

from typing import Any, Optional

from app.repositories.base import OrgScopedRepository, serialize, utcnow


class ChannelConnectionRepository(OrgScopedRepository):
    """Connection records. Credentials are stored encrypted and never serialized
    to API responses by the routes that read them."""

    collection_name = "channel_connections"

    async def get_for_provider(self, organization_id: str, provider: str) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(self._scope(organization_id, {"provider": provider}))
        return serialize(doc)

    async def upsert_for_provider(
        self, organization_id: str, provider: str, data: dict[str, Any]
    ) -> dict[str, Any]:
        now = utcnow()
        doc = await self.collection.find_one_and_update(
            self._scope(organization_id, {"provider": provider}),
            {"$set": {**data, "updated_at": now}, "$setOnInsert": {"created_at": now}},
            upsert=True,
            return_document=True,
        )
        return serialize(doc)  # type: ignore[return-value]

    async def update_status(
        self, organization_id: str, provider: str, fields: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one_and_update(
            self._scope(organization_id, {"provider": provider}),
            {"$set": {**fields, "updated_at": utcnow()}},
            return_document=True,
        )
        return serialize(doc)

    async def delete_for_provider(self, organization_id: str, provider: str) -> bool:
        result = await self.collection.delete_one(self._scope(organization_id, {"provider": provider}))
        return result.deleted_count > 0

    async def list_active(self, provider: str) -> list[dict[str, Any]]:
        """Cross-organization scan, used ONLY by the background scheduler."""
        cursor = self.collection.find({"provider": provider, "status": "connected"})
        return [serialize(doc) for doc in await cursor.to_list(length=1000)]
