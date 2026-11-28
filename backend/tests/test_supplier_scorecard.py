"""Supplier performance scorecard: worked examples checked by hand, then the flow through the API."""
from datetime import datetime, timedelta, timezone

from app.services.procurement.reliability import compute_reliability

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def po(status="delivered", on_time=True, received=None, rejected=None, invoice=None, total=1000.0, days_ago=10, **extra):
    """One PO of two lines (100 and 50 ordered). `received`/`rejected` are per line; None means no receipt recorded."""
    doc = {"status": status, "on_time": on_time if status in ("delivered", "closed") else None,
           "issued_at": NOW - timedelta(days=days_ago + 5), "delivered_at": NOW - timedelta(days=days_ago),
           "lines": [{"quantity": 100}, {"quantity": 50}], "pricing": {"total": total}, **extra}
    if received is not None:
        doc["receipt"] = {"lines": [{"received_quantity": r, "rejected_quantity": j} for r, j in zip(received, rejected or (0, 0))],
                          "invoice_amount": invoice}
    return doc


def test_perfect_supplier_scores_100():
    card = compute_reliability([po(received=(100, 50), invoice=1000) for _ in range(4)], now=NOW)
    assert card["status"] == "rated" and card["band"] == "good" and card["score"] == 1.0
    assert set(card["factors"]) == {"on_time_in_full", "quality", "fulfilment", "commercial"}
    assert "On time and in full for 4 of 4 orders" in card["reasons"]


def test_new_supplier_has_no_score_not_a_low_one():
    card = compute_reliability([po(), po()], now=NOW)
    assert card["score"] is None and card["status"] == "new" and card["band"] == "new"
    assert card["notes"] == ["New supplier: 2 of the 3 completed orders needed for a score."]
    assert compute_reliability(now=NOW)["status"] == "new"


def test_missing_factors_are_left_out_not_counted_as_zero():
    # Only delivery dates recorded: on-time 2 of 3, fulfilment 3 of 3. Weights 0.30 and 0.15 renormalise.
    card = compute_reliability([po(), po(), po(on_time=False)], now=NOW)
    assert set(card["factors"]) == {"on_time_in_full", "fulfilment"}
    assert card["score"] == round((2 / 3 * 0.30 + 1.0 * 0.15) / 0.45, 4)  # 0.7778
    assert "left out" in card["notes"][1] and "Product quality" in card["notes"][1]


def test_short_delivery_and_rejections():
    orders = [po(received=(100, 40), rejected=(10, 0)), po(received=(100, 50)), po(received=(100, 50))]
    card = compute_reliability(orders, now=NOW)
    assert card["factors"]["on_time_in_full"]["score"] == round(2 / 3, 4)  # the 40-of-50 line is not in full
    # Rejection rates per line: 10%, 0, 0, 0, 0, 0 -> mean 1.667%; 5 points per 1% -> 0.9167
    assert card["factors"]["quality"]["score"] == round(1 - 5 * (0.1 / 6), 4)
    assert "1.7% of quantity rejected" in card["factors"]["quality"]["reason"]


def test_only_supplier_cancellations_count():
    orders = [po(), po(), po(), po(status="cancelled", cancelled_by="supplier"),
              po(status="cancelled", cancelled_by="buyer"), po(status="cancelled", cancelled_by="supplier", issued_at=None)]
    card = compute_reliability(orders, now=NOW)
    assert card["factors"]["fulfilment"]["score"] == 0.75  # 3 delivered, 1 dropped by the supplier after issue
    assert card["factors"]["fulfilment"]["reason"] == "Delivered 3 of 4 orders; cancelled 1"


def test_invoice_over_the_order_total_is_flagged():
    orders = [po(received=(100, 50), invoice=1001.5), po(received=(100, 50), invoice=1100), po(received=(100, 50), invoice=900)]
    assert compute_reliability(orders, now=NOW)["factors"]["commercial"]["score"] == round(2 / 3, 4)  # ₹1.5 over is rounding


def test_responsiveness_from_quote_requests():
    rfqs = [{"procurement_request_id": "r1", "sent_at": NOW - timedelta(days=30)},
            {"procurement_request_id": "r2", "sent_at": NOW - timedelta(days=30)},
            {"procurement_request_id": "r3", "sent_at": NOW - timedelta(days=20)},
            {"procurement_request_id": "r4", "sent_at": NOW - timedelta(days=3)}]   # still within the reply window
    quotations = [{"procurement_request_id": "r1", "created_at": NOW - timedelta(days=29)},   # 1 day  -> 1.0
                  {"procurement_request_id": "r2", "created_at": NOW - timedelta(days=22)}]   # 8 days -> 0.5
    factor = compute_reliability([po()] * 3, rfqs, quotations, now=NOW)["factors"]["responsiveness"]
    assert factor["score"] == 0.5 and factor["n"] == 3  # (1 + 0.5 + 0 for no reply) / 3
    assert factor["reason"] == "Quote requests: replied in 4.5 days on average; no reply to 1 (3 requests)"


def test_only_recent_orders_count():
    old_bad = [po(on_time=False, days_ago=400 + i) for i in range(20)]
    recent_good = [po(days_ago=i) for i in range(20)]
    assert compute_reliability(old_bad + recent_good, now=NOW)["factors"]["on_time_in_full"]["score"] == 1.0


# --- through the API -------------------------------------------------------------------------------------------


async def _issued_po(api, s):
    h = s["headers"]
    po_doc = (await api.post(f"/api/v1/comparisons/procurement-requests/{s['request']['id']}/award", headers=h,
                             json={"quotation_id": s["q_shree"]["id"]})).json()
    for action in ("approve", "issue"):
        assert (await api.post(f"/api/v1/purchase-orders/{po_doc['id']}/{action}", headers=h)).status_code == 200
    return po_doc


async def test_receipt_cancellation_and_scorecard_through_the_api(api, sourcing):
    h = sourcing["headers"]
    supplier_url = f"/api/v1/suppliers/{sourcing['shree']['id']}"
    assert (await api.get(supplier_url, headers=h)).json()["reliability"]["status"] == "new"

    for received in ((100, 500), (100, 500), (100, 450)):
        po_doc = await _issued_po(api, sourcing)
        delivered = await api.post(f"/api/v1/purchase-orders/{po_doc['id']}/deliver", headers=h, json={
            "receipt": {"lines": [{"received_quantity": received[0]}, {"received_quantity": received[1], "rejected_quantity": 5}],
                        "invoice_amount": po_doc["pricing"]["total"]}})
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()["receipt"]["in_full"] is (received[1] == 500)
    cancelled = await _issued_po(api, sourcing)
    assert (await api.post(f"/api/v1/purchase-orders/{cancelled['id']}/cancel", headers=h,
                           json={"cancelled_by": "supplier", "cancel_reason": "Out of stock"})).json()["cancelled_by"] == "supplier"

    card = (await api.get(supplier_url, headers=h)).json()["reliability"]
    assert card["status"] == "rated" and card["sample_size"] == 4
    assert card["factors"]["fulfilment"]["score"] == 0.75
    assert card["factors"]["commercial"]["score"] == 1.0
    assert any("in full" in reason for reason in card["reasons"])

    # The stored score is what comparisons and the supplier list read.
    listed = {s["name"]: s["reliability"] for s in (await api.get("/api/v1/suppliers", headers=h)).json()["items"]}
    assert listed["Shree Steel"]["status"] == "rated" and listed["Apex Metals"]["status"] == "new"
    compared = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}", headers=h,
                               json={"include_ai_explanation": False})).json()
    rows = {r["supplier_name"]: r for r in compared["suppliers"]}
    assert rows["Shree Steel"]["reliability_status"] == "rated" and rows["Shree Steel"]["reliability_reasons"]
    apex = rows["Apex Metals"]
    assert apex["reliability_status"] == "new" and apex["reliability_score"] is None
    criterion = next(c for c in apex["criteria"] if c["criterion"] == "reliability")
    assert criterion["score"] == 0.5 and "New supplier" in criterion["deductions"][0]
    assert "supplier_reliability" not in apex["missing_data"]


async def test_receipt_is_validated(api, sourcing):
    h = sourcing["headers"]
    po_doc = await _issued_po(api, sourcing)
    url = f"/api/v1/purchase-orders/{po_doc['id']}/receipt"
    lines = [{"received_quantity": 100}, {"received_quantity": 500}]
    assert (await api.put(url, headers=h, json={"lines": lines})).status_code == 409  # not delivered yet
    await api.post(f"/api/v1/purchase-orders/{po_doc['id']}/deliver", headers=h)
    assert (await api.put(url, headers=h, json={"lines": lines[:1]})).status_code == 409  # a line missing
    assert (await api.put(url, headers=h, json={"lines": [{"received_quantity": 5, "rejected_quantity": 6}, lines[1]]})).status_code == 409
    assert (await api.put(url, headers=h, json={"lines": [{"received_quantity": -1}, lines[1]]})).status_code == 422
    ok = await api.put(url, headers=h, json={"lines": lines, "invoice_amount": 100})
    assert ok.status_code == 200 and ok.json()["receipt"]["in_full"] is True
