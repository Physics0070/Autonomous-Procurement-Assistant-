"""Supplier performance scorecard: how a supplier has actually performed for this organization.

Rule-based and explainable, not a machine-learning prediction (the late-delivery model is reported separately as
`reliability.ml`). Every factor comes from records a person makes in the app; nothing here is inferred from how well
we read the supplier's documents.

  on-time in full   30%  delivered POs with a receipt: delivered by the expected date AND accepted >= ordered on
                         every line (accepted = received - rejected). With no receipts, on-time alone is used and the
                         factor is marked partial: in-full is then unknown, never assumed.
  quality           30%  quantity-weighted rejection rate, total rejected / total received, over receipts
  fulfilment        15%  issued POs delivered, against those the supplier cancelled (our cancellations are ignored)
  commercial        15%  final invoices on comparable orders: correct, overbilled or underbilled against the PO total
                         (or an approved revised amount); partial invoices and credit notes are not scored
  responsiveness    10%  days from the first quote request to the supplier's emailed quotation (the email's own time);
                         uploads without a trustworthy received time are not timed

Evidence and confidence: a missing factor is left out and the weights of the rest are scaled up to sum to 1; the
scaled weights are reported (`applied_weight`), and the factor contributions add up exactly to the score. How much of
the full weight is backed by records is `coverage` (a partial factor counts half). Fewer than MIN_ASSESSED_ORDERS
assessed orders: "new", no score. Below FULL_COVERAGE or MIN_CONFIDENT_ORDERS: "provisional".
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

WEIGHTS = {"on_time_in_full": 0.30, "quality": 0.30, "fulfilment": 0.15, "commercial": 0.15, "responsiveness": 0.10}
LABELS = {"on_time_in_full": "On-time, in-full delivery", "quality": "Product quality", "fulfilment": "Order fulfilment",
          "commercial": "Commercial reliability", "responsiveness": "Responsiveness"}
METHOD = "scorecard"
VERSION = 3  # 3: per-round RFQ timing, zero invoices not scored
MIN_ASSESSED_ORDERS = 3          # delivered + cancelled by the supplier, before any score is shown
MIN_CONFIDENT_ORDERS = 5         # below this the score is provisional
FULL_COVERAGE = 0.6              # share of the full weight that must be backed by records for a non-provisional score
RECENT_ORDERS = 20               # only the latest orders count, so a supplier can recover
REJECTION_PENALTY = 5            # each 1% of quantity rejected costs 5 points; 20% rejected scores 0
INVOICE_TOLERANCE = (2.0, 0.005)  # ₹2 or 0.5% either way, for rounding
REPLY_FULL_DAYS, REPLY_ZERO_DAYS = 2, 14  # a quotation within 2 days scores 1, after 14 days (or none) 0
BANDS = ((0.75, "good"), (0.50, "ok"), (0.0, "attention"))

DELIVERED = ("delivered", "closed")


def _when(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return _when(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            try:
                return _when(parsedate_to_datetime(value))  # an email Date header
            except (TypeError, ValueError, IndexError):
                return None
    return None


def _order_time(po: dict) -> datetime:
    return _when(po.get("delivered_at")) or _when(po.get("cancelled_at")) or _when(po.get("issued_at")) \
        or _when(po.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)


def _quantity(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def receipt_lines(po: dict) -> Optional[list[tuple[float, float, float]]]:
    """(ordered, received, rejected) for every PO line, or None when no complete, valid receipt is recorded.

    Lines are matched by their `line` index (older receipts, without one, by position when the counts agree). Any
    gap, duplicate, negative or non-numeric quantity, or more rejected than received makes the receipt unusable:
    a broken receipt is treated as missing, never as a good delivery.
    """
    po_lines = po.get("lines") or []
    recorded = (po.get("receipt") or {}).get("lines") or []
    if not po_lines or len(recorded) != len(po_lines):
        return None
    if all("line" in r for r in recorded):
        by_index = {r["line"]: r for r in recorded}
        if sorted(by_index) != list(range(len(po_lines))):
            return None
        recorded = [by_index[i] for i in range(len(po_lines))]
    out = []
    for line, r in zip(po_lines, recorded):
        ordered, received, rejected = (_quantity(line.get("quantity")), _quantity(r.get("received_quantity")),
                                       _quantity(r.get("rejected_quantity", 0)))
        if ordered is None or received is None or rejected is None or rejected > received:
            return None
        out.append((ordered, received, rejected))
    return out


def delivered_in_full(lines: list[tuple[float, float, float]]) -> bool:
    """Accepted (received - rejected) covers what was ordered on every line."""
    return all(received - rejected >= ordered for ordered, received, rejected in lines)


def _factor(score: float, n: int, reason: str, partial: bool = False) -> dict[str, Any]:
    return {"score": round(min(max(score, 0.0), 1.0), 4), "n": n, "reason": reason, "partial": partial}


def _on_time_in_full(delivered: list[dict]) -> Optional[dict]:
    timed = [po for po in delivered if po.get("on_time") is not None]
    if not timed:
        return None
    receipted = [(po, receipt_lines(po)) for po in timed]
    receipted = [(po, lines) for po, lines in receipted if lines is not None]
    if receipted:
        good = sum(1 for po, lines in receipted if po["on_time"] and delivered_in_full(lines))
        reason = f"On time and in full for {good} of {len(receipted)} orders with quantities recorded"
        if len(receipted) < len(timed):
            reason += f" ({len(timed) - len(receipted)} more delivered without quantities, not counted)"
        return _factor(good / len(receipted), len(receipted), reason)
    on_time = sum(1 for po in timed if po["on_time"])
    return _factor(on_time / len(timed), len(timed), f"On time for {on_time} of {len(timed)} orders; "
                   "quantities received not recorded, so in-full is unknown", partial=True)


def _quality(delivered: list[dict]) -> Optional[dict]:
    received = rejected = 0.0
    inspected = 0
    for po in delivered:
        lines = receipt_lines(po)
        if lines and sum(rec for _, rec, _ in lines) > 0:
            inspected += 1
            received += sum(rec for _, rec, _ in lines)
            rejected += sum(rej for _, _, rej in lines)
    if not inspected:
        return None
    rate = rejected / received
    return _factor(1 - REJECTION_PENALTY * rate, inspected,
                   f"{rate:.1%} of quantity rejected at inspection ({rejected:g} of {received:g}, {inspected} orders)")


def _supplier_cancelled(po: dict) -> bool:
    return po.get("status") == "cancelled" and bool(po.get("issued_at")) and po.get("cancelled_by") == "supplier"


def _fulfilment(orders: list[dict]) -> Optional[dict]:
    done = sum(1 for po in orders if po.get("status") in DELIVERED)
    dropped = sum(1 for po in orders if _supplier_cancelled(po))
    if not done + dropped:
        return None
    reason = f"Delivered {done} of {done + dropped} orders" + (f"; the supplier cancelled {dropped}" if dropped else "")
    return _factor(done / (done + dropped), done + dropped, reason)


def invoice_check(po: dict) -> str:
    """correct | overbilled | underbilled for a comparable final invoice; otherwise why it is not scored."""
    receipt = po.get("receipt") or {}
    amount = _quantity(receipt.get("invoice_amount"))
    if amount is None:
        return "none"
    if amount == 0:
        return "invalid"  # a zero invoice is a recording error or a free supply, not evidence of underbilling
    kind = receipt.get("invoice_type") or "final"
    if kind != "final":
        return kind  # partial | credit_note: not comparable with the order total
    baseline = _quantity(receipt.get("approved_amount"))  # an approved variation replaces the PO total
    if baseline is None:
        lines = receipt_lines(po)
        if lines is None or not delivered_in_full(lines):
            return "not_comparable"  # a short delivery changes what should be billed
        baseline = _quantity((po.get("pricing") or {}).get("total"))
        if baseline is None:
            return "not_comparable"
    absolute, relative = INVOICE_TOLERANCE
    tolerance = max(absolute, baseline * relative)
    if amount > baseline + tolerance:
        return "overbilled"
    if amount < baseline - tolerance:
        return "underbilled"
    return "correct"


def _commercial(delivered: list[dict]) -> Optional[dict]:
    checks = [invoice_check(po) for po in delivered]
    scored = [c for c in checks if c in ("correct", "overbilled", "underbilled")]
    skipped = {kind: checks.count(kind) for kind in ("partial", "credit_note", "not_comparable", "invalid") if checks.count(kind)}
    if not scored:
        return None
    correct = scored.count("correct")
    reason = f"Invoice matched the order on {correct} of {len(scored)}"
    wrong = [f"{scored.count(k)} {k}" for k in ("overbilled", "underbilled") if scored.count(k)]
    if wrong:
        reason += f" ({', '.join(wrong)})"
    if skipped:
        names = {"partial": "partial invoice", "credit_note": "credit note", "not_comparable": "short delivery",
                 "invalid": "zero invoice"}
        reason += "; not scored: " + ", ".join(f"{n} {names[k]}{'s' if n > 1 else ''}" for k, n in skipped.items())
    return _factor(correct / len(scored), len(scored), reason)


def reply_time(quotation: dict) -> Optional[datetime]:
    """When the supplier's quotation reached us, from the email itself; None when no trustworthy time is known
    (manual uploads: their processing time says nothing about when the supplier answered)."""
    metadata = (quotation.get("source") or {}).get("metadata") or {}
    return _when(metadata.get("received_at")) if metadata.get("channel") == "gmail" else None


def _rounds(sends: list[datetime], replies: list[datetime]) -> list[tuple[datetime, Optional[datetime]]]:
    """Pair each quote-request round with its reply. A send while an earlier one is still unanswered is a reminder
    and keeps the first send's clock; a send after a reply opens a new round; a reply with no open round (a second
    quotation, or mail before any request) is not counted again."""
    events = sorted([(t, 0) for t in sends] + [(t, 1) for t in replies])  # on a tie the send comes first
    rounds: list[list] = []
    for when, kind in events:
        open_round = rounds and rounds[-1][1] is None
        if kind == 0 and not open_round:
            rounds.append([when, None])
        elif kind == 1 and open_round:
            rounds[-1][1] = when
    return [(sent, answered) for sent, answered in rounds]


def _responsiveness(rfqs: list[dict], quotations: list[dict], now: datetime) -> Optional[dict]:
    sends: dict[str, list[datetime]] = {}
    for rfq in rfqs:
        request, sent = str(rfq.get("procurement_request_id") or ""), _when(rfq.get("sent_at"))
        if request and sent:
            sends.setdefault(request, []).append(sent)
    timed: dict[str, list[datetime]] = {}
    untimed_requests: set[str] = set()
    for q in quotations:
        request, when = str(q.get("procurement_request_id") or ""), reply_time(q)
        if when is None:
            untimed_requests.add(request)
        else:
            timed.setdefault(request, []).append(when)
    scores, days, silent, untimed = [], [], 0, 0
    for request, request_sends in sends.items():
        for sent, answered in _rounds(request_sends, timed.get(request, [])):
            if answered is not None:
                waited = (answered - sent).total_seconds() / 86400
                days.append(waited)
                scores.append(1 - (min(max(waited, REPLY_FULL_DAYS), REPLY_ZERO_DAYS) - REPLY_FULL_DAYS)
                              / (REPLY_ZERO_DAYS - REPLY_FULL_DAYS))
            elif request in untimed_requests:
                untimed += 1  # answered by an upload with no known reply time: not timed, not silence
            elif (now - sent).total_seconds() / 86400 >= REPLY_ZERO_DAYS:
                silent += 1
                scores.append(0.0)
    if not scores:
        return None
    parts = [f"replied in {sum(days) / len(days):.1f} days on average"] if days else []
    if silent:
        parts.append(f"no reply to {silent}")
    reason = f"Quote requests: {'; '.join(parts)} ({len(scores)} requests)"
    if untimed:
        reason += f"; {untimed} replied with no known reply time, not timed"
    return _factor(sum(scores) / len(scores), len(scores), reason)


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

    delivered_count = len(delivered)
    cancelled_count = sum(1 for po in recent if _supplier_cancelled(po))
    assessed = delivered_count + cancelled_count
    coverage = round(sum(WEIGHTS[n] * (0.5 if f["partial"] else 1.0) for n, f in factors.items()), 4)
    total_weight = sum(WEIGHTS[n] for n in factors)
    for name, factor in factors.items():
        factor["label"], factor["weight"] = LABELS[name], WEIGHTS[name]
        factor["applied_weight"] = round(WEIGHTS[name] / total_weight, 4)
        factor["contribution"] = round(factor["score"] * WEIGHTS[name] / total_weight, 4)

    orders_text = f"{assessed} orders assessed: {delivered_count} delivered" + (
        f", {cancelled_count} cancelled by the supplier" if cancelled_count else "")
    base = {"method": METHOD, "version": VERSION, "sample_size": assessed, "delivered_orders": delivered_count,
            "supplier_cancellations": cancelled_count, "coverage": coverage, "factors": factors,
            "reasons": [f["reason"] for f in factors.values()], "weights": WEIGHTS, "is_ml_prediction": False}
    if assessed < MIN_ASSESSED_ORDERS:
        return {**base, "score": None, "status": "new", "band": "new", "confidence": "none",
                "notes": [f"New supplier: {orders_text}; {MIN_ASSESSED_ORDERS} are needed for a score."]}

    score = round(sum(f["contribution"] for f in factors.values()), 4)  # exactly the sum of what is displayed
    provisional = coverage < FULL_COVERAGE or assessed < MIN_CONFIDENT_ORDERS
    notes = [f"{orders_text}. Records cover {coverage:.0%} of the full scorecard weight."]
    missing = [LABELS[n] for n in WEIGHTS if n not in factors]
    if missing:
        notes.append(f"Not recorded, so left out and the other weights scaled up: {', '.join(missing)}.")
    if provisional:
        notes.append("Provisional: too little evidence for a firm rating.")
    return {**base, "score": score, "status": "provisional" if provisional else "rated",
            "band": next(band for floor, band in BANDS if score >= floor),
            "confidence": "low" if provisional else "high", "notes": notes}


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
                                          {"supplier_id": 1, "procurement_request_id": 1, "created_at": 1, "source.metadata": 1})),
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
    """Recompute every supplier scored by an older method or version (run once at startup)."""
    orgs = await db.suppliers.distinct("organization_id", {"reliability.version": {"$ne": VERSION}})
    for org in orgs:
        await refresh_reliability(db, str(org))
    return len(orgs)
