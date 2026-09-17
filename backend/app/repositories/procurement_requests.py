from __future__ import annotations

from typing import Any, Optional

from app.repositories.base import OrgScopedRepository, maybe_object_id, serialize


class ProcurementRequestRepository(OrgScopedRepository):
    collection_name = "procurement_requests"

    async def list_with_counts(
        self,
        organization_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Requests plus a live quotation count, via one aggregation."""
        match = self._scope(organization_id, {"status": status} if status else None)
        pipeline: list[dict[str, Any]] = [
            {"$match": match},
            {"$sort": {"created_at": -1}},
            {"$skip": max(skip, 0)},
            {"$limit": max(min(limit, 500), 1)},
            {
                "$lookup": {
                    "from": "quotations",
                    "localField": "_id",
                    "foreignField": "procurement_request_id",
                    "as": "_quotations",
                }
            },
            {"$addFields": {"quotation_count": {"$size": "$_quotations"}}},
            {"$project": {"_quotations": 0}},
        ]
        docs = await self.collection.aggregate(pipeline).to_list(length=limit)
        return [serialize(d) for d in docs]

    async def status_counts(self, organization_id: str) -> dict[str, int]:
        pipeline = [
            {"$match": self._scope(organization_id)},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        docs = await self.collection.aggregate(pipeline).to_list(length=50)
        return {str(d["_id"]): int(d["count"]) for d in docs}
