from __future__ import annotations

from typing import Any, Optional

from app.repositories.base import OrgScopedRepository, serialize, to_object_id


class SupplierRepository(OrgScopedRepository):
    collection_name = "suppliers"

    async def find_by_name(self, organization_id: str, name: str) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(
            self._scope(organization_id, {"name": {"$regex": f"^{_escape(name)}$", "$options": "i"}})
        )
        return serialize(doc)

    async def find_by_email(self, organization_id: str, email: str) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(
            self._scope(organization_id, {"email": email.lower().strip()})
        )
        return serialize(doc)

    async def find_by_gst(self, organization_id: str, gst: str) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(
            self._scope(organization_id, {"gst_number": gst.upper().strip()})
        )
        return serialize(doc)

    async def all_names(self, organization_id: str) -> list[dict[str, Any]]:
        cursor = self.collection.find(self._scope(organization_id), {"name": 1, "email": 1, "gst_number": 1})
        return [serialize(d) for d in await cursor.to_list(length=1000)]

    async def set_reliability(
        self, organization_id: str, supplier_id: str, reliability: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return await self.raw_update(organization_id, supplier_id, {"$set": {"reliability": reliability}})

    async def search(self, organization_id: str, query: str, limit: int = 50) -> list[dict[str, Any]]:
        cursor = self.collection.find(
            self._scope(organization_id, {"name": {"$regex": _escape(query), "$options": "i"}})
        ).limit(limit)
        return [serialize(d) for d in await cursor.to_list(length=limit)]


def _escape(value: str) -> str:
    specials = r"\.^$*+?()[]{}|"
    out = []
    for ch in value:
        if ch in specials:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)
