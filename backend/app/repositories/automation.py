"""Communications (RFQ / negotiation / PO drafts) and purchase orders."""
from __future__ import annotations

from typing import Any, Optional

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
