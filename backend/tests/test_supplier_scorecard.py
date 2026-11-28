"""Supplier scorecard and comparison scoring: worked examples checked by hand, then the flows through the API.

Every expected number below is derived in the comment beside it from the raw observations in the test.
"""
import math
from datetime import datetime, timedelta, timezone

import pytest

from app.services.procurement.comparison import build_comparison, tax_basis, validate_weights
from app.services.procurement.reliability import compute_reliability, invoice_check, receipt_lines

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def po(status="delivered", on_time=True, received=None, rejected=None, invoice=None, total=1000.0, days_ago=10,
       ordered=(100, 50), **extra):
    """A PO with one line per `ordered` quantity. `received`/`rejected` are per line; None means no receipt."""
    doc = {"status": status, "on_time": on_time if status in ("delivered", "closed") else None,
           "issued_at": NOW - timedelta(days=days_ago + 5), "delivered_at": NOW - timedelta(days=days_ago),
           "lines": [{"quantity": q} for q in ordered], "pricing": {"total": total}}
    receipt = extra.pop("receipt", {})
    doc.update(extra)
    if received is not None:
        rejected = rejected or (0,) * len(received)
        doc["receipt"] = {"lines": [{"line": i, "received_quantity": r, "rejected_quantity": j}
                                    for i, (r, j) in enumerate(zip(received, rejected))],
                          "invoice_amount": invoice, **receipt}
    return doc


def full(**kw):
    return po(received=(100, 50), invoice=1000, **kw)


def contributions_add_up(card):
    assert math.isclose(sum(f["applied_weight"] for f in card["factors"].values()), 1.0, abs_tol=2e-4)
    assert card["score"] == round(sum(f["contribution"] for f in card["factors"].values()), 4)
    for f in card["factors"].values():
        assert f["contribution"] == round(f["score"] * f["weight"] / sum(g["weight"] for g in card["factors"].values()), 4)


# --- P0: reliability correctness -------------------------------------------------------------------------------


def test_perfect_supplier_with_enough_evidence_is_rated():
    card = compute_reliability([full() for _ in range(5)], now=NOW)
    assert (card["status"], card["confidence"], card["band"], card["score"]) == ("rated", "high", "good", 1.0)
    assert card["coverage"] == 0.9  # every factor but responsiveness (0.10): 0.30 + 0.30 + 0.15 + 0.15
    assert card["factors"]["quality"]["applied_weight"] == round(0.30 / 0.90, 4)  # scaled-up weight is exposed
    contributions_add_up(card)


def test_four_perfect_orders_are_only_provisional():
    card = compute_reliability([full() for _ in range(4)], now=NOW)
    assert card["status"] == "provisional" and card["confidence"] == "low" and card["score"] == 1.0


def test_on_time_orders_without_receipts_are_never_in_full():
    card = compute_reliability([po() for _ in range(5)], now=NOW)
    otif = card["factors"]["on_time_in_full"]
    assert otif["partial"] is True and "in-full is unknown" in otif["reason"] and "and in full" not in otif["reason"]
    assert card["coverage"] == 0.3  # on-time only counts half of its 0.30, plus fulfilment 0.15
    assert card["status"] == "provisional"
    assert "quality" not in card["factors"] and "commercial" not in card["factors"]


def test_receipted_orders_decide_otif_and_unreceipted_ones_are_not_counted_as_in_full():
    card = compute_reliability([full(), full(), po(received=(100, 40)), po(), po()], now=NOW)
    otif = card["factors"]["on_time_in_full"]
    assert otif["score"] == round(2 / 3, 4) and otif["n"] == 3 and otif["partial"] is False
    assert "2 more delivered without quantities, not counted" in otif["reason"]


def test_partial_delivery_and_rejections_use_accepted_quantity():
    # Line 1: 100 received, 10 rejected -> accepted 90 < 100 ordered: not in full, though every unit arrived.
    assert receipt_lines(po(received=(100, 50), rejected=(10, 0))) == [(100, 100, 10), (50, 50, 0)]
    card = compute_reliability([po(received=(100, 50), rejected=(10, 0)), full(), full()], now=NOW)
    assert card["factors"]["on_time_in_full"]["score"] == round(2 / 3, 4)


def test_quality_is_weighted_by_quantity_not_averaged_per_line():
    # Unequal lines: 10 of 1000 rejected and 5 of 10 rejected. Weighted: 15 / 1010 = 1.485% -> 1 - 5 x 0.01485.
    # (A mean of line rates, (1% + 50%) / 2 = 25.5%, would wrongly score 0.)
    order = po(ordered=(1000, 10), received=(1000, 10), rejected=(10, 5))
    quality = compute_reliability([order, full(), full()], now=NOW)["factors"]["quality"]
    # Over all three orders: rejected 15, received 1000 + 10 + 150 + 150 = 1310 -> 1 - 5 x 15/1310.
    assert quality["score"] == round(1 - 5 * 15 / 1310, 4) and quality["n"] == 3
    assert "(15 of 1310, 3 orders)" in quality["reason"]
    single = compute_reliability([order] * 3, now=NOW)["factors"]["quality"]
    assert single["score"] == round(1 - 5 * 15 / 1010, 4)


def test_quality_missing_everywhere_is_left_out():
    card = compute_reliability([po() for _ in range(5)], now=NOW)
    assert "quality" not in card["factors"]
    assert any("Product quality" in note for note in card["notes"])


def test_broken_receipts_count_as_missing_never_as_good():
    gap = po(received=(100, 50))
    gap["receipt"]["lines"] = gap["receipt"]["lines"][:1]                     # a line missing
    dup = po(received=(100, 50))
    dup["receipt"]["lines"][1]["line"] = 0                                    # the same line twice
    over = po(received=(100, 50), rejected=(101, 0))                          # more rejected than received
    neg = po(received=(100, -5))
    nan = po(received=(100, float("nan")))
    for broken in (gap, dup, over, neg, nan):
        assert receipt_lines(broken) is None
    legacy = {"lines": [{"quantity": 2}], "receipt": {"lines": [{"received_quantity": 2, "rejected_quantity": 0}]}}
    assert receipt_lines(legacy) == [(2, 2, 0)]  # older receipts without line numbers, matched by position


def test_three_supplier_cancellations_are_not_three_completed_orders():
    cancelled = [po(status="cancelled", cancelled_by="supplier", cancelled_at=NOW - timedelta(days=i)) for i in range(3)]
    card = compute_reliability(cancelled, now=NOW)
    assert card["sample_size"] == 3 and card["delivered_orders"] == 0 and card["supplier_cancellations"] == 3
    assert card["notes"][0].startswith("3 orders assessed: 0 delivered, 3 cancelled by the supplier")
    assert set(card["factors"]) == {"fulfilment"} and card["score"] == 0.0
    assert card["status"] == "provisional" and card["coverage"] == 0.15  # one metric: never a firm rating


def test_buyer_cancellations_and_never_issued_orders_do_not_count():
    orders = [full(), full(), full(), po(status="cancelled", cancelled_by="buyer"),
              po(status="cancelled", cancelled_by="supplier", issued_at=None)]
    card = compute_reliability(orders, now=NOW)
    assert card["factors"]["fulfilment"]["score"] == 1.0 and card["sample_size"] == 3


def test_new_supplier_has_no_score():
    card = compute_reliability([full(), full()], now=NOW)
    assert card["score"] is None and card["status"] == "new" and card["confidence"] == "none"
    assert compute_reliability(now=NOW)["status"] == "new"


def test_only_recent_orders_count():
    old_bad = [full(on_time=False, days_ago=400 + i) for i in range(20)]
    recent_good = [full(days_ago=i) for i in range(20)]
    assert compute_reliability(old_bad + recent_good, now=NOW)["factors"]["on_time_in_full"]["score"] == 1.0


# --- P1: commercial and responsiveness evidence ----------------------------------------------------------------


def test_invoices_are_classified_and_only_comparable_final_ones_scored():
    assert invoice_check(full()) == "correct"
    assert invoice_check(po(received=(100, 50), invoice=1001.5)) == "correct"           # rounding
    assert invoice_check(po(received=(100, 50), invoice=1100)) == "overbilled"
    assert invoice_check(po(received=(100, 50), invoice=900)) == "underbilled"
    assert invoice_check(po(received=(100, 50), invoice=400, receipt={"invoice_type": "partial"})) == "partial"
    assert invoice_check(po(received=(100, 50), invoice=50, receipt={"invoice_type": "credit_note"})) == "credit_note"
    assert invoice_check(po(received=(100, 40), invoice=800)) == "not_comparable"       # short delivery
    assert invoice_check(po(received=(100, 50), invoice=1100, receipt={"approved_amount": 1100})) == "correct"
    assert invoice_check(po()) == "none"

    orders = [full(), po(received=(100, 50), invoice=900), po(received=(100, 50), invoice=1100),
              po(received=(100, 50), invoice=400, receipt={"invoice_type": "partial"})]
    commercial = compute_reliability(orders, now=NOW)["factors"]["commercial"]
    assert commercial["score"] == round(1 / 3, 4) and commercial["n"] == 3
    assert commercial["reason"] == "Invoice matched the order on 1 of 3 (1 overbilled, 1 underbilled); not scored: 1 partial invoice"


def emailed(request, days_after_first_send, synced_days_later=0):
    received = NOW - timedelta(days=30) + timedelta(days=days_after_first_send)
    return {"procurement_request_id": request, "created_at": received + timedelta(days=synced_days_later),
            "source": {"metadata": {"channel": "gmail", "received_at": received.strftime("%a, %d %b %Y %H:%M:%S +0000")}}}


def test_repeated_rfq_sends_count_once_from_the_first_send():
    rfqs = [{"procurement_request_id": "r1", "sent_at": NOW - timedelta(days=30)},
            {"procurement_request_id": "r1", "sent_at": NOW - timedelta(days=25)}]   # reminder
    replies = [emailed("r1", 2), emailed("r1", 6)]                                  # second quotation: not counted again
    factor = compute_reliability([full()] * 3, rfqs, replies, now=NOW)["factors"]["responsiveness"]
    assert factor["n"] == 1 and factor["score"] == 1.0  # 2 days from the first send
    assert factor["reason"] == "Quote requests: replied in 2.0 days on average (1 requests)"


def test_delayed_gmail_sync_uses_the_email_time_not_processing_time():
    rfqs = [{"procurement_request_id": "r1", "sent_at": NOW - timedelta(days=30)}]
    factor = compute_reliability([full()] * 3, rfqs, [emailed("r1", 1, synced_days_later=12)], now=NOW)["factors"]["responsiveness"]
    assert factor["score"] == 1.0  # replied in 1 day although it was imported 12 days later


def test_uploads_without_a_received_time_are_not_timed_and_silence_scores_zero():
    rfqs = [{"procurement_request_id": "r1", "sent_at": NOW - timedelta(days=30)},
            {"procurement_request_id": "r2", "sent_at": NOW - timedelta(days=30)},
            {"procurement_request_id": "r3", "sent_at": NOW - timedelta(days=30)},
            {"procurement_request_id": "r4", "sent_at": NOW - timedelta(days=3)}]    # still inside the window
    quotations = [emailed("r1", 8),                                                 # 8 days -> 1 - (8-2)/12 = 0.5
                  {"procurement_request_id": "r2", "created_at": NOW - timedelta(days=29), "source": {}},  # manual upload
                  {**emailed("r3", -1)}]                                             # arrived before the request: not a reply
    factor = compute_reliability([full()] * 3, rfqs, quotations, now=NOW)["factors"]["responsiveness"]
    assert factor["n"] == 2 and factor["score"] == 0.25  # (0.5 + 0 for r3, no reply after sending) / 2
    assert "1 replied with no known reply time, not timed" in factor["reason"]


# --- P1: comparison ---------------------------------------------------------------------------------------------


REQUEST = {"id": "req1", "title": "Paper", "currency": "INR", "items": [{"item_id": "i1", "name": "A4", "quantity": 10}]}


def quote(qid, *, subtotal=1000.0, total=None, tax_pct=None, tax_amount=None, currency="INR", delivery=7, payment=30,
          anomaly=None, validation=None, corrections=None, freight=None):
    item = {"line_id": "L1", "quantity": 10, "unit_price": subtotal / 10, "total_price": subtotal}
    if anomaly:
        item["attributes"] = {"_price_anomaly": {"status": anomaly}}
    pricing = {"currency": currency, "subtotal": subtotal, "total_amount": total, "tax_percentage": tax_pct,
               "tax_amount": tax_amount, "transportation_cost": freight}
    pricing["landed_total"] = total
    return {"id": qid, "supplier_name": qid, "processing_status": "COMPLETED",
            "effective_data": {"items": [item], "pricing": pricing, "delivery": {"delivery_days": delivery},
                               "payment_terms": {"payment_days": payment}},
            "match_result": {"matched_count": 1, "coverage": 1.0},
            "validation": validation or {}, "user_corrections": corrections or []}


def rows(result):
    return {s.supplier_name: s for s in result.suppliers}


def test_tax_rate_alone_does_not_make_a_total_inclusive():
    assert tax_basis(quote("a", total=1180, tax_pct=18)["effective_data"])[:2] == ("inclusive", 1180)
    assert tax_basis(quote("b", total=1000, tax_pct=18)["effective_data"])[:2] == ("exclusive", 1180.0)  # "GST extra"
    assert tax_basis(quote("c", total=1000)["effective_data"])[0] == "unknown"
    assert tax_basis(quote("d", total=1050, tax_pct=18)["effective_data"])[0] == "unknown"  # does not reconcile
    assert tax_basis(quote("e", total=1280, tax_pct=18, freight=100)["effective_data"])[:2] == ("inclusive", 1280)


def test_tax_extra_quotation_is_compared_with_gst_added():
    # 'extra' prints 1,000 + 18% GST extra = 1,180 really; 'incl' prints 1,150 including GST. 'incl' is cheaper.
    result = build_comparison(REQUEST, [quote("extra", total=1000, tax_pct=18), quote("incl", subtotal=974.58, total=1150, tax_pct=18)])
    r = rows(result)
    assert r["extra"].tax_basis == "exclusive" and r["extra"].comparable_price == 1180.0
    price = {name: next(c for c in s.criteria if c.criterion == "price") for name, s in r.items()}
    assert price["incl"].score == 1.0 and price["extra"].score == 0.0
    assert any("GST of 180.00 added" in d for d in price["extra"].deductions)


def test_unknown_tax_basis_is_left_off_the_price_scale_when_others_are_known():
    result = build_comparison(REQUEST, [quote("known", total=1180, tax_pct=18), quote("unclear", total=900)])
    price = next(c for c in rows(result)["unclear"].criteria if c.criterion == "price")
    assert price.data_available is False and "tax" in rows(result)["unclear"].missing_data


def test_mixed_currencies_are_not_priced_against_each_other_or_recommended():
    result = build_comparison(REQUEST, [quote("usd", subtotal=10, total=11.8, tax_pct=18, currency="USD", delivery=1, payment=90),
                                        quote("inr", total=1180, tax_pct=18)])
    r = rows(result)
    assert r["usd"].requires_review and "convert to INR" in r["usd"].review_reasons[0]
    assert next(c for c in r["usd"].criteria if c.criterion == "price").data_available is False
    assert result.recommended_supplier_name == "inr"
    assert any("not in INR" in w for w in result.warnings)


def test_high_anomaly_top_quotation_is_not_recommended_as_awardable():
    result = build_comparison(REQUEST, [quote("cheap", subtotal=100, total=118, tax_pct=18, anomaly="HIGH_ANOMALY"),
                                        quote("normal", total=1180, tax_pct=18)])
    assert result.suppliers[0].supplier_name == "cheap" and result.suppliers[0].requires_review
    assert result.recommended_supplier_name == "normal"
    assert any("ranks first but needs review" in w for w in result.warnings)


def test_ocr_validation_errors_do_not_cost_the_supplier_points():
    issue = {"field": "items.0", "code": "line_total_mismatch", "severity": "warning", "message": "Line total does not match."}
    clean = rows(build_comparison(REQUEST, [quote("a", total=1180, tax_pct=18)]))["a"]
    flagged = rows(build_comparison(REQUEST, [quote("a", total=1180, tax_pct=18,
                                                    validation={"issues": [issue], "error_count": 3, "warning_count": 4})]))["a"]
    assert flagged.overall_score == clean.overall_score
    assert flagged.unverified_issues == 1 and not flagged.confirmed_supplier_errors
    assert any("may be reading errors" in w for w in flagged.warnings)
    # After a person reviewed the quotation and left that line as read, it is the supplier's own error: shown, not scored.
    reviewed = rows(build_comparison(REQUEST, [quote("a", total=1180, tax_pct=18, validation={"issues": [issue]},
                                                     corrections=[{"path": "delivery.delivery_days"}])]))["a"]
    assert reviewed.confirmed_supplier_errors == ["Line total does not match."]
    assert reviewed.overall_score == clean.overall_score


def test_weight_overrides_are_validated():
    assert validate_weights({"price": 2}) == {"price": 2.0}
    for bad in ({"speed": 1}, {"price": -1}, {"price": float("nan")}, {"price": "high"}, {"price": True}):
        with pytest.raises(ValueError):
            validate_weights(bad)
    with pytest.raises(ValueError):
        build_comparison(REQUEST, [quote("a")], weight_overrides={"bogus": 1})


# --- through the API -------------------------------------------------------------------------------------------


async def _issued_po(api, s, quotation="q_shree"):
    h = s["headers"]
    created = await api.post(f"/api/v1/comparisons/procurement-requests/{s['request']['id']}/award", headers=h,
                             json={"quotation_id": s[quotation]["id"]})
    assert created.status_code == 201, created.text
    po_doc = created.json()
    for action in ("approve", "issue"):
        assert (await api.post(f"/api/v1/purchase-orders/{po_doc['id']}/{action}", headers=h)).status_code == 200
    return po_doc


def _receipt(received, rejected=(0, 0), **invoice):
    return {"lines": [{"line": i, "received_quantity": r, "rejected_quantity": j}
                      for i, (r, j) in enumerate(zip(received, rejected))], **invoice}


async def test_receipt_cancellation_and_scorecard_through_the_api(api, sourcing):
    h = sourcing["headers"]
    supplier_url = f"/api/v1/suppliers/{sourcing['shree']['id']}"
    assert (await api.get(supplier_url, headers=h)).json()["reliability"]["status"] == "new"

    for received in ((100, 500), (100, 500), (100, 450)):
        po_doc = await _issued_po(api, sourcing)
        delivered = await api.post(f"/api/v1/purchase-orders/{po_doc['id']}/deliver", headers=h, json={
            "receipt": _receipt(received, (0, 5), invoice_amount=po_doc["pricing"]["total"])})
        assert delivered.status_code == 200, delivered.text
        assert delivered.json()["receipt"]["in_full"] is False  # 5 rejected leaves 495 accepted of 500 ordered
        assert delivered.json()["receipt"]["lines"][1]["accepted_quantity"] == received[1] - 5
    cancelled = await _issued_po(api, sourcing)
    assert (await api.post(f"/api/v1/purchase-orders/{cancelled['id']}/cancel", headers=h,
                           json={"cancelled_by": "supplier", "cancel_reason": "Out of stock"})).json()["cancelled_by"] == "supplier"

    card = (await api.get(supplier_url, headers=h)).json()["reliability"]
    assert card["status"] == "provisional" and card["sample_size"] == 4 and card["delivered_orders"] == 3
    assert card["factors"]["fulfilment"]["score"] == 0.75
    assert card["factors"]["on_time_in_full"]["score"] == 0.0  # none accepted in full
    # Invoices equal the PO total, but the orders were not accepted in full: not comparable, so not scored.
    assert "commercial" not in card["factors"]
    assert card["score"] == round(sum(f["contribution"] for f in card["factors"].values()), 4)

    listed = {s["name"]: s["reliability"] for s in (await api.get("/api/v1/suppliers", headers=h)).json()["items"]}
    assert listed["Shree Steel"]["status"] == "provisional" and listed["Apex Metals"]["status"] == "new"
    compared = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}", headers=h,
                               json={"include_ai_explanation": False})).json()
    shree = {r["supplier_name"]: r for r in compared["suppliers"]}["Shree Steel"]
    criterion = next(c for c in shree["criteria"] if c["criterion"] == "reliability")
    assert shree["reliability_status"] == "provisional" and "Provisional score" in criterion["deductions"][0]
    expected = 0.5 + (card["score"] - 0.5) * card["coverage"]  # moved from neutral in proportion to the evidence
    assert criterion["score"] == round(expected, 4)


async def test_receipt_is_validated(api, sourcing):
    h = sourcing["headers"]
    po_doc = await _issued_po(api, sourcing)
    url = f"/api/v1/purchase-orders/{po_doc['id']}/receipt"
    good = _receipt((100, 500))
    assert (await api.put(url, headers=h, json=good)).status_code == 409  # not delivered yet
    await api.post(f"/api/v1/purchase-orders/{po_doc['id']}/deliver", headers=h)
    missing = {"lines": good["lines"][:1]}
    duplicate = {"lines": [good["lines"][0], {**good["lines"][1], "line": 0}]}
    out_of_range = {"lines": [good["lines"][0], {**good["lines"][1], "line": 7}]}
    over = _receipt((5, 500), (6, 0))
    for body in (missing, duplicate, out_of_range, over):
        assert (await api.put(url, headers=h, json=body)).status_code == 409, body
    for line in ({"line": 0, "received_quantity": -1}, {"line": 0, "received_quantity": "Infinity"},
                 {"line": 0, "received_quantity": "NaN"}, {"received_quantity": 1}):
        assert (await api.put(url, headers=h, json={"lines": [line, good["lines"][1]]})).status_code == 422, line
    assert (await api.put(url, headers=h, json={**good, "invoice_type": "estimate"})).status_code == 422
    ok = await api.put(url, headers=h, json={"lines": list(reversed(good["lines"])), "invoice_amount": 100,
                                             "invoice_type": "partial"})
    assert ok.status_code == 200 and ok.json()["receipt"]["in_full"] is True
    assert [line["line"] for line in ok.json()["receipt"]["lines"]] == [0, 1]  # stored by line, not by position sent


async def test_unknown_weight_overrides_are_rejected_by_the_api(api, sourcing):
    url = f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}"
    for weights in ({"speed": 1}, {"price": -1}, {"price": 0, "delivery": 0, "payment": 0, "reliability": 0, "other": 0}):
        response = await api.post(url, headers=sourcing["headers"], json={"weights": weights, "include_ai_explanation": False})
        assert response.status_code == 422, weights


async def test_award_of_a_quotation_flagged_for_review_needs_confirmation(api, db, sourcing):
    from bson import ObjectId

    h = sourcing["headers"]
    await db.quotations.update_one({"_id": ObjectId(sourcing["q_apex"]["id"])},
                                   {"$set": {"effective_data.pricing.currency": "USD"}})
    compared = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}", headers=h,
                               json={"include_ai_explanation": False})).json()
    assert compared["recommended_supplier_name"] == "Shree Steel"
    url = f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/award"
    refused = await api.post(url, headers=h, json={"quotation_id": sourcing["q_apex"]["id"]})
    assert refused.status_code == 409 and "needs review" in refused.text
    confirmed = await api.post(url, headers=h, json={"quotation_id": sourcing["q_apex"]["id"], "confirm_review": True})
    assert confirmed.status_code == 201
    assert [e["action"] for e in confirmed.json()["history"]] == ["created", "review_confirmed"]
