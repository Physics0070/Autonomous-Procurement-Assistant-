from __future__ import annotations

from typing import Any, Optional

from app.repositories.base import OrgScopedRepository, maybe_object_id, serialize, to_object_id, utcnow


class QuotationRepository(OrgScopedRepository):
    collection_name = "quotations"

    async def list_filtered(
        self,
        organization_id: str,
        *,
        status: Optional[str] = None,
        procurement_request_id: Optional[str] = None,
        supplier_id: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        filters: dict[str, Any] = {}
        if status:
            filters["processing_status"] = status
        if procurement_request_id:
            filters["procurement_request_id"] = to_object_id(procurement_request_id, "procurement_request_id")
        if supplier_id:
            filters["supplier_id"] = to_object_id(supplier_id, "supplier_id")
        # Heavy blobs are excluded from list responses.
        projection = {"raw_content": 0, "ai_extraction.raw_response": 0}
        cursor = (
            self.collection.find(self._scope(organization_id, filters), projection)
            .sort([("created_at", -1)])
            .skip(max(skip, 0))
            .limit(max(min(limit, 500), 1))
        )
        return [serialize(d) for d in await cursor.to_list(length=limit)]

    async def find_by_external_reference(
        self, organization_id: str, external_reference: str
    ) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(
            self._scope(organization_id, {"source.external_reference": external_reference}),
            {"raw_content": 0, "ai_extraction.raw_response": 0},
        )
        return serialize(doc)

    async def for_request(self, organization_id: str, procurement_request_id: str) -> list[dict[str, Any]]:
        cursor = self.collection.find(
            self._scope(
                organization_id,
                {"procurement_request_id": to_object_id(procurement_request_id, "procurement_request_id")},
            ),
            {"raw_content": 0, "ai_extraction.raw_response": 0},
        )
        return [serialize(d) for d in await cursor.to_list(length=500)]

    async def set_status(
        self,
        organization_id: str,
        quotation_id: str,
        status: str,
        message: str = "",
        details: Optional[dict[str, Any]] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        """Set status and append to the immutable processing history."""
        update: dict[str, Any] = {
            "$set": {"processing_status": status, **(extra or {})},
            "$push": {
                "processing_history": {
                    "status": status,
                    "message": message,
                    "at": utcnow(),
                    "details": details or {},
                }
            },
        }
        return await self.raw_update(organization_id, quotation_id, update)

    async def store_stage(
        self, organization_id: str, quotation_id: str, field: str, value: Any
    ) -> Optional[dict[str, Any]]:
        return await self.raw_update(organization_id, quotation_id, {"$set": {field: value}})

    async def append_corrections(
        self, organization_id: str, quotation_id: str, corrections: list[dict[str, Any]], effective: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """Store corrections as history + a derived effective view.

        `normalized_data` and `ai_extraction` are never mutated here.
        """
        return await self.raw_update(
            organization_id,
            quotation_id,
            {
                "$push": {"user_corrections": {"$each": corrections}},
                "$set": {"effective_data": effective},
            },
        )

    async def status_counts(self, organization_id: str) -> dict[str, int]:
        pipeline = [
            {"$match": self._scope(organization_id)},
            {"$group": {"_id": "$processing_status", "count": {"$sum": 1}}},
        ]
        docs = await self.collection.aggregate(pipeline).to_list(length=50)
        return {str(d["_id"]): int(d["count"]) for d in docs}

    async def pending_processing(self, limit: int = 50) -> list[dict[str, Any]]:
        """Cross-organization scan used ONLY by the recovery sweep at startup."""
        cursor = self.collection.find(
            {"processing_status": {"$in": ["UPLOADED", "QUEUED", "EXTRACTING", "AI_EXTRACTING", "NORMALIZING"]}},
            {"_id": 1, "organization_id": 1},
        ).limit(limit)
        return [serialize(d) for d in await cursor.to_list(length=limit)]

    async def recent_activity(self, organization_id: str, limit: int = 10) -> list[dict[str, Any]]:
        cursor = (
            self.collection.find(
                self._scope(organization_id),
                {
                    "source.original_filename": 1,
                    "processing_status": 1,
                    "created_at": 1,
                    "supplier_name": 1,
                    "normalized_data.pricing.total_amount": 1,
                },
            )
            .sort([("created_at", -1)])
            .limit(limit)
        )
        return [serialize(d) for d in await cursor.to_list(length=limit)]


class ComparisonRepository(OrgScopedRepository):
    collection_name = "comparisons"

    async def upsert_for_request(
        self, organization_id: str, procurement_request_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        query = self._scope(
            organization_id,
            {"procurement_request_id": to_object_id(procurement_request_id, "procurement_request_id")},
        )
        payload = dict(payload)
        payload.update(query)
        payload["updated_at"] = utcnow()
        payload.setdefault("created_at", utcnow())
        doc = await self.collection.find_one_and_update(
            query, {"$set": payload}, upsert=True, return_document=True
        )
        return serialize(doc)  # type: ignore[return-value]

    async def latest_for_request(
        self, organization_id: str, procurement_request_id: str
    ) -> Optional[dict[str, Any]]:
        doc = await self.collection.find_one(
            self._scope(
                organization_id,
                {"procurement_request_id": to_object_id(procurement_request_id, "procurement_request_id")},
            )
        )
        return serialize(doc)


class PriceHistoryRepository(OrgScopedRepository):
    """Observed unit prices, used for the price-anomaly baseline."""

    collection_name = "price_history"

    async def record(
        self,
        organization_id: str,
        normalized_name: str,
        unit_price: float,
        *,
        unit: Optional[str] = None,
        supplier_id: Optional[str] = None,
        quotation_id: Optional[str] = None,
    ) -> None:
        await self.collection.insert_one(
            {
                "organization_id": to_object_id(organization_id, "organization_id"),
                "normalized_name": normalized_name,
                "unit": unit,
                "unit_price": float(unit_price),
                "supplier_id": maybe_object_id(supplier_id),
                "quotation_id": maybe_object_id(quotation_id),
                "created_at": utcnow(),
            }
        )

    async def prices(self, organization_id: str, normalized_name: str, limit: int = 1000) -> list[float]:
        cursor = self.collection.find(self._scope(organization_id, {"normalized_name": normalized_name}),
                                      {"unit_price": 1}).sort("created_at", -1).limit(limit)
        return [d["unit_price"] for d in await cursor.to_list(length=limit)]

    async def stats(self, organization_id: str, normalized_name: str) -> Optional[dict[str, Any]]:
        pipeline = [
            {"$match": self._scope(organization_id, {"normalized_name": normalized_name})},
            {
                "$group": {
                    "_id": "$normalized_name",
                    "mean": {"$avg": "$unit_price"},
                    "stdev": {"$stdDevSamp": "$unit_price"},
                    "min": {"$min": "$unit_price"},
                    "max": {"$max": "$unit_price"},
                    "count": {"$sum": 1},
                }
            },
        ]
        docs = await self.collection.aggregate(pipeline).to_list(length=1)
        if not docs:
            return None
        d = docs[0]
        return {
            "mean": d.get("mean"),
            "stdev": d.get("stdev"),
            "min": d.get("min"),
            "max": d.get("max"),
            "count": int(d.get("count", 0)),
        }
