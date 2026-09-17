"""Dashboard metrics, computed from real collections only.

Every number here is a live count or aggregate. Nothing is synthesised to make
the dashboard look busier than the data warrants.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, quotation_repo, request_repo, supplier_repo
from app.repositories.quotations import QuotationRepository
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import ProcessingStatus, ProcurementStatus
from app.workers.processing import get_processing_queue

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_IN_PROGRESS = {
    ProcessingStatus.UPLOADED.value,
    ProcessingStatus.QUEUED.value,
    ProcessingStatus.EXTRACTING.value,
    ProcessingStatus.AI_EXTRACTING.value,
    ProcessingStatus.NORMALIZING.value,
}


@router.get("/summary")
async def summary(
    context: CurrentUser,
    requests: ProcurementRequestRepository = Depends(request_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
) -> dict[str, Any]:
    org = context.organization_id

    request_statuses = await requests.status_counts(org)
    quotation_statuses = await quotations.status_counts(org)

    total_requests = sum(request_statuses.values())
    active_requests = sum(
        count
        for status, count in request_statuses.items()
        if status in (ProcurementStatus.OPEN.value, ProcurementStatus.COMPARING.value)
    )

    total_quotations = sum(quotation_statuses.values())
    completed = quotation_statuses.get(ProcessingStatus.COMPLETED.value, 0)
    requires_review = quotation_statuses.get(ProcessingStatus.REQUIRES_REVIEW.value, 0)
    failed = quotation_statuses.get(ProcessingStatus.FAILED.value, 0)
    in_progress = sum(count for status, count in quotation_statuses.items() if status in _IN_PROGRESS)
    # A quotation needing review has still been fully processed - counting only
    # COMPLETED here would report "0 processed" for a pipeline that ran fine.
    processed = completed + requires_review

    supplier_count = await suppliers.count(org)
    recent = await quotations.recent_activity(org, limit=8)

    # Quotations received per day over the last 14 days, for the trend chart.
    since = datetime.now(timezone.utc) - timedelta(days=13)
    pipeline = [
        {"$match": {**quotations._scope(org), "created_at": {"$gte": since}}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    rows = await quotations.collection.aggregate(pipeline).to_list(length=40)
    by_day = {row["_id"]: int(row["count"]) for row in rows}
    trend = []
    for offset in range(13, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=offset)).strftime("%Y-%m-%d")
        trend.append({"date": day, "quotations": by_day.get(day, 0)})

    total_value = 0.0
    value_rows = await quotations.collection.aggregate(
        [
            {
                "$match": {
                    **quotations._scope(org),
                    "processing_status": {
                        "$in": [ProcessingStatus.COMPLETED.value, ProcessingStatus.REQUIRES_REVIEW.value]
                    },
                }
            },
            {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
        ]
    ).to_list(length=1)
    if value_rows and value_rows[0].get("total"):
        total_value = float(value_rows[0]["total"])

    queue = get_processing_queue()

    return {
        "procurement_requests": {
            "total": total_requests,
            "active": active_requests,
            "by_status": request_statuses,
        },
        "quotations": {
            "total": total_quotations,
            "processed": processed,
            "completed": completed,
            "requires_review": requires_review,
            "in_progress": in_progress,
            "failed": failed,
            "by_status": quotation_statuses,
        },
        "suppliers": {"total": supplier_count},
        "value": {"quoted_total": round(total_value, 2), "currency": "INR"},
        "queue": {"depth": queue.depth(), "in_flight": queue.in_flight()},
        "trend": trend,
        "recent_activity": [
            {
                "quotation_id": str(row.get("id")),
                "filename": ((row.get("source") or {}).get("original_filename")),
                "supplier_name": row.get("supplier_name"),
                "status": row.get("processing_status"),
                "created_at": row.get("created_at"),
                "total_amount": (
                    ((row.get("normalized_data") or {}).get("pricing") or {}).get("total_amount")
                ),
            }
            for row in recent
        ],
    }
