"""Communications (RFQ / negotiation / PO drafts) and purchase orders."""
from __future__ import annotations

from typing import Any, Optional

from app.core.errors import ConflictError
from app.repositories.base import OrgScopedRepository, serialize, to_object_id


class CommunicationRepository(OrgScopedRepository):
    collection_name = "communications"


class PurchaseOrderRepository(OrgScopedRepository):
    collection_name = "purchase_orders"

    async def find_all(self, organization_id: str, filters: Optional[dict[str, Any]] = None,
                       fields: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Every matching PO (analytics needs the full history, not a page). History is left out."""
        projection = dict.fromkeys(fields, 1) if fields else {"history": 0}
        cursor = self.collection.find(self._scope(organization_id, filters), projection)
        return [serialize(d) for d in await cursor.to_list(length=None)]

    async def live_award(self, organization_id: str, procurement_request_id: str) -> Optional[dict[str, Any]]:
        """The request's purchase order that is not cancelled, if any (older orders carry no award_key)."""
        doc = await self.collection.find_one(self._scope(organization_id, {
            "procurement_request_id": str(procurement_request_id), "status": {"$ne": "cancelled"}}), {"history": 0})
        return serialize(doc)

    async def create_award(self, organization_id: str, po: dict[str, Any]) -> tuple[Optional[dict], Optional[dict]]:
        """(created, None), or (None, the existing live order) when the request already has one. Two awards racing
        each other cannot both succeed: the unique award_key index lets exactly one insert through."""
        request_id = str(po["procurement_request_id"])
        existing = await self.live_award(organization_id, request_id)
        if existing:
            return None, existing
        try:
            return await self.create(organization_id, {**po, "award_key": request_id}), None
        except ConflictError:
            existing = await self.live_award(organization_id, request_id)
            if existing:
                return None, existing
            raise

    async def next_po_number(self, organization_id: str, year: int) -> str:
        """PO-<year>-<0001>, from an atomic per-organization counter."""
        doc = await self.db.counters.find_one_and_update(
            {"organization_id": to_object_id(organization_id), "name": f"po-{year}"},
            {"$inc": {"value": 1}},
            upsert=True,
            return_document=True,
        )
        return f"PO-{year}-{doc['value']:04d}"


class AgentRunRepository(OrgScopedRepository):
    collection_name = "agent_runs"


class ConversationRepository(OrgScopedRepository):
    collection_name = "conversations"
