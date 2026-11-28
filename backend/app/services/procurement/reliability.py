"""Supplier performance scorecard: how a supplier has actually performed for this organization.

Rule-based and explainable, not a machine-learning prediction (the late-delivery model is reported separately as
`reliability.ml`). Every factor comes from the organization's own records:

  on-time in full   30%  delivered POs: delivered by the expected date, and every line received in full
  quality           30%  quantity rejected at inspection, from the receipt recorded at delivery
  fulfilment        15%  issued POs that were delivered, against those the supplier cancelled
  commercial        15%  invoice amount within the PO total
  responsiveness    10%  days from a sent quote request to the supplier's quotation

A factor with no data is left out and its weight shared among the others; it never counts as zero. A supplier needs
MIN_COMPLETED_ORDERS completed orders before it gets a score at all; until then it is a "new supplier". The supplier
is never marked down for our own failures: extraction problems are not counted, and an order we cancelled is ignored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

WEIGHTS = {"on_time_in_full": 0.30, "quality": 0.30, "fulfilment": 0.15, "commercial": 0.15, "responsiveness": 0.10}
LABELS = {"on_time_in_full": "On-time, in-full delivery", "quality": "Product quality", "fulfilment": "Order fulfilment",
          "commercial": "Commercial reliability", "responsiveness": "Responsiveness"}
METHOD = "scorecard"
MIN_COMPLETED_ORDERS = 3
RECENT_ORDERS = 20               # only the latest orders count, so a supplier can recover
REJECTION_PENALTY = 5            # each 1% of quantity rejected costs 5 points; 20% rejected scores 0
INVOICE_TOLERANCE = (2.0, 0.005)  # ₹2 or 0.5% over the PO total, for rounding
REPLY_FULL_DAYS, REPLY_ZERO_DAYS = 2, 14  # a quotation within 2 days scores 1, after 14 days (or none) 0
BANDS = ((0.75, "good"), (0.50, "ok"), (0.0, "attention"))

DELIVERED = ("delivered", "closed")


def _when(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return _when(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _order_time(po: dict) -> datetime:
    return _when(po.get("delivered_at")) or _when(po.get("issued_at")) or _when(po.get("created_at")) \
        or datetime.min.replace(tzinfo=timezone.utc)


def _factor(score: float, n: int, reason: str) -> dict[str, Any]:
    return {"score": round(min(max(score, 0.0), 1.0), 4), "n": n, "reason": reason}


def _receipt_lines(po: dict) -> list[tuple[float, float, float]]:
    """(ordered, received, rejected) per line, when a receipt was recorded."""
    receipt = (po.get("receipt") or {}).get("lines")
    if not receipt:
        return []
    return [(float(line.get("quantity") or 0), float(r.get("received_quantity") or 0), float(r.get("rejected_quantity") or 0))
            for line, r in zip(po.get("lines") or [], receipt)]


def _on_time_in_full(delivered: list[dict]) -> Optional[dict]:
    timed = [po for po in delivered if po.get("on_time") is not None]
    if not timed:
        return None
    with_receipt = [po for po in timed if _receipt_lines(po)]
    good = sum(1 for po in timed if po["on_time"] and all(rec >= ordered for ordered, rec, _ in _receipt_lines(po)))
    reason = f"On time{' and in full' if with_receipt else ''} for {good} of {len(timed)} orders"
    if with_receipt and len(with_receipt) < len(timed):
        reason += f" (quantities recorded for {len(with_receipt)})"
    return _factor(good / len(timed), len(timed), reason)


def _quality(delivered: list[dict]) -> Optional[dict]:
    rates = [rej / rec for po in delivered for _, rec, rej in _receipt_lines(po) if rec > 0]
    if not rates:
        return None
    rate = sum(rates) / len(rates)
    orders = sum(1 for po in delivered if _receipt_lines(po))
    return _factor(1 - REJECTION_PENALTY * rate, orders, f"{rate:.1%} of quantity rejected at inspection ({orders} orders)")


def _fulfilment(orders: list[dict]) -> Optional[dict]:
    done = sum(1 for po in orders if po.get("status") in DELIVERED)
    dropped = sum(1 for po in orders if po.get("status") == "cancelled" and po.get("issued_at")
                  and po.get("cancelled_by") == "supplier")
    if not done + dropped:
        return None
    reason = f"Delivered {done} of {done + dropped} orders" + (f"; cancelled {dropped}" if dropped else "")
    return _factor(done / (done + dropped), done + dropped, reason)


def _commercial(delivered: list[dict]) -> Optional[dict]:
    invoiced = [po for po in delivered if (po.get("receipt") or {}).get("invoice_amount") is not None]
    if not invoiced:
        return None
    absolute, relative = INVOICE_TOLERANCE

    def within(po: dict) -> bool:
        total = float((po.get("pricing") or {}).get("total") or 0)
        return float(po["receipt"]["invoice_amount"]) <= total + max(absolute, total * relative)

    ok = sum(1 for po in invoiced if within(po))
    reason = f"Invoice within the order total on {ok} of {len(invoiced)} orders"
    return _factor(ok / len(invoiced), len(invoiced), reason)


def _responsiveness(rfqs: list[dict], quotations: list[dict], now: datetime) -> Optional[dict]:
    first_reply: dict[str, datetime] = {}
    for q in quotations:
        request, created = str(q.get("procurement_request_id") or ""), _when(q.get("created_at"))
        if request and created and (request not in first_reply or created < first_reply[request]):
            first_reply[request] = created
    scores, days, silent = [], [], 0
    for rfq in rfqs:
        sent = _when(rfq.get("sent_at"))
        if sent is None:
            continue
        reply = first_reply.get(str(rfq.get("procurement_request_id") or ""))
        waited = ((reply or now) - sent).total_seconds() / 86400
        if reply is None and waited < REPLY_ZERO_DAYS:
            continue  # still within the reply window: no verdict yet
        if reply is None:
            silent += 1
        else:
            days.append(max(waited, 0))
        scores.append(0.0 if reply is None else
                      1 - (min(max(waited, REPLY_FULL_DAYS), REPLY_ZERO_DAYS) - REPLY_FULL_DAYS) / (REPLY_ZERO_DAYS - REPLY_FULL_DAYS))
    if not scores:
        return None
    parts = [f"replied in {sum(days) / len(days):.1f} days on average"] if days else []
    if silent:
        parts.append(f"no reply to {silent}")
    return _factor(sum(scores) / len(scores), len(scores), f"Quote requests: {'; '.join(parts)} ({len(scores)} requests)")


def compute_reliability(orders: Optional[list[dict]] = None, rfqs: Optional[list[dict]] = None,
                        quotations: Optional[list[dict]] = None, *, now: Optional[datetime] = None) -> dict[str, Any]:
    """The scorecard for one supplier from its purchase orders, sent quote requests and quotations."""
    now = now or datetime.now(timezone.utc)
    recent = sorted(orders or [], key=_order_time, reverse=True)[:RECENT_ORDERS]
    delivered = [po for po in recent if po.get("status") in DELIVERED]
    factors = {name: f for name, f in (
        ("on_time_in_full", _on_time_in_full(delivered)), ("quality", _quality(delivered)),
        ("fulfilment", _fulfilment(recent)), ("commercial", _commercial(delivered)),
        ("responsiveness", _responsiveness(rfqs or [], quotations or [], now))) if f is not None}
    for name, factor in factors.items():
        factor["label"], factor["weight"] = LABELS[name], WEIGHTS[name]

    completed = (factors.get("fulfilment") or {}).get("n", 0)
    reasons = [f["reason"] for f in factors.values()]
    if completed < MIN_COMPLETED_ORDERS:
        return {"score": None, "status": "new", "band": "new", "method": METHOD, "sample_size": completed,
                "factors": factors, "reasons": reasons, "weights": WEIGHTS, "is_ml_prediction": False,
                "notes": [f"New supplier: {completed} of the {MIN_COMPLETED_ORDERS} completed orders needed for a score."]}

    total_weight = sum(WEIGHTS[name] for name in factors)
    score = round(sum(f["score"] * WEIGHTS[name] for name, f in factors.items()) / total_weight, 4)
    missing = [LABELS[name] for name in WEIGHTS if name not in factors]
    notes = [f"Based on the latest {completed} completed orders."]
    if missing:
        notes.append(f"Not yet recorded, so left out: {', '.join(missing)}.")
    return {"score": score, "status": "rated", "band": next(band for floor, band in BANDS if score >= floor),
            "method": METHOD, "sample_size": completed, "factors": factors, "reasons": reasons,
            "weights": WEIGHTS, "is_ml_prediction": False, "notes": notes}


async def refresh_reliability(db, organization_id: str, supplier_ids: Optional[list[str]] = None) -> dict[str, dict]:
    """Recompute and store the scorecard for the given suppliers (all of the organization's when None)."""
    from app.repositories.base import maybe_object_id, to_object_id

    org = to_object_id(organization_id)
    scope: dict[str, Any] = {"organization_id": org}
    if supplier_ids is not None:
        if not supplier_ids:
            return {}
        scope["_id"] = {"$in": [maybe_object_id(i) for i in supplier_ids]}
    ids = [str(s["_id"]) async for s in db.suppliers.find(scope, {"_id": 1})]
    if not ids:
        return {}
    either = {"$in": [*ids, *(maybe_object_id(i) for i in ids)]}  # supplier ids are stored as text or ObjectId
    grouped: dict[str, dict[str, list]] = {i: {"orders": [], "rfqs": [], "quotations": []} for i in ids}
    sources = (
        ("orders", db.purchase_orders.find({"organization_id": org, "supplier_id": either}, {"history": 0, "lines.description": 0})),
        ("rfqs", db.communications.find({"organization_id": org, "supplier_id": either, "kind": "rfq", "sent_at": {"$ne": None}},
                                        {"supplier_id": 1, "procurement_request_id": 1, "sent_at": 1})),
        ("quotations", db.quotations.find({"organization_id": org, "supplier_id": either},
                                          {"supplier_id": 1, "procurement_request_id": 1, "created_at": 1})),
    )
    for key, cursor in sources:
        async for doc in cursor:
            bucket = grouped.get(str(doc.get("supplier_id")))
            if bucket is not None:
                bucket[key].append(doc)
    results = {}
    for supplier_id, data in grouped.items():
        results[supplier_id] = compute_reliability(data["orders"], data["rfqs"], data["quotations"])
        await db.suppliers.update_one({"_id": maybe_object_id(supplier_id), "organization_id": org},
                                      {"$set": {"reliability": results[supplier_id]}})
    return results


async def refresh_stale_reliability(db) -> int:
    """Recompute every supplier still carrying a score from an older method (run once at startup)."""
    orgs = await db.suppliers.distinct("organization_id", {"reliability.method": {"$ne": METHOD}})
    for org in orgs:
        await refresh_reliability(db, str(org))
    return len(orgs)
