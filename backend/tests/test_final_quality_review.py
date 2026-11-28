"""Final quality review: mixed GST basis, line-level inspection coverage across units, comparison freshness,
round-specific RFQ response matching. Written before the fixes and run against the unchanged code first (see
docs/SCORING_FIX_VERIFICATION.md, "Final quality review"). Every expected number is derived beside it.
"""
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.services.procurement.comparison import build_comparison
from app.services.procurement.reliability import compute_reliability

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
REQUEST = {"id": "req", "title": "t", "currency": "INR", "items": [{"item_id": "i1", "name": "A4", "quantity": 10}]}


def quote(qid, *, total, tax_pct=None, subtotal=1000.0, text=""):
    return {"id": qid, "supplier_name": qid, "processing_status": "COMPLETED", "raw_content": {"raw_text": text},
            "effective_data": {"items": [{"line_id": "L1", "quantity": 10, "unit_price": subtotal / 10, "total_price": subtotal}],
                               "pricing": {"currency": "INR", "subtotal": subtotal, "total_amount": total,
                                           "landed_total": total, "tax_percentage": tax_pct},
                               "delivery": {"delivery_days": 7}, "payment_terms": {"payment_days": 30}},
            "match_result": {"matched_count": 1, "coverage": 1.0}}


# --- 1. mixed GST basis --------------------------------------------------------------------------------------------


def test_unknown_gst_basis_beside_known_ones_needs_review_and_is_not_recommended():
    inclusive = quote("inclusive", total=1180, tax_pct=18)            # 1000 + 18% = 1180: total includes GST
    exclusive = quote("exclusive", total=1000, tax_pct=18)            # total = net, 18% stated: GST extra -> 1180
    unknown = quote("unknown", total=900, subtotal=900)               # no GST figures, no wording: basis unknown
    result = build_comparison(REQUEST, [inclusive, exclusive, unknown])
    rows = {s.supplier_name: s for s in result.suppliers}
    assert rows["inclusive"].tax_basis == "inclusive" and rows["exclusive"].tax_basis == "exclusive"
    assert rows["unknown"].tax_basis == "unknown"
    assert rows["unknown"].requires_review is True
    assert any("includes GST" in r for r in rows["unknown"].review_reasons)
    assert not rows["inclusive"].requires_review and not rows["exclusive"].requires_review
    assert result.recommended_quotation_id in ("inclusive", "exclusive")


async def test_unknown_gst_quotation_cannot_be_awarded_without_confirmation(api, db, sourcing):
    h, url = sourcing["headers"], f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}"
    # Apex's GST figures removed: its total no longer shows whether GST is included. Shree's still does.
    await db.quotations.update_one({"_id": ObjectId(sourcing["q_apex"]["id"])}, {"$set": {
        "effective_data.pricing.tax_percentage": None, "effective_data.items.0.tax_percentage": None,
        "effective_data.pricing.total_amount": 7600.0, "effective_data.pricing.landed_total": 7600.0}})
    await api.post(url, headers=h, json={"include_ai_explanation": False})
    refused = await api.post(f"{url}/award", headers=h, json={"quotation_id": sourcing["q_apex"]["id"]})
    assert refused.status_code == 409, refused.text
    confirmed = await api.post(f"{url}/award", headers=h, json={"quotation_id": sourcing["q_apex"]["id"], "confirm_review": True})
    assert confirmed.status_code == 201, confirmed.text


# --- 2. quality inspection coverage --------------------------------------------------------------------------------


def mixed_po(inspected=(True, True, False), rejected=(0, 2, 0), priced=True):
    units = (("kg", 1000, 10.0), ("litre", 10, 500.0), ("pcs", 100, 1.0))
    lines = [{"quantity": q, "unit": u, **({"unit_price": p} if priced else {})} for u, q, p in units]
    receipt = [{"line": i, "received_quantity": q, "inspected": done, "rejected_quantity": rej if done else None}
               for i, ((_, q, _), done, rej) in enumerate(zip(units, inspected, rejected))]
    return {"status": "delivered", "on_time": True, "issued_at": NOW - timedelta(days=20),
            "delivered_at": NOW - timedelta(days=10), "lines": lines, "pricing": {"total": 15100.0},
            "receipt": {"lines": receipt}}


def test_one_inspected_line_does_not_make_the_order_inspected():
    quality = compute_reliability([mixed_po()] * 3, now=NOW)["factors"]["quality"]
    # 2 of 3 lines inspected on each order -> line-level evidence 6 / 9.
    assert quality["evidence"] == round(6 / 9, 4) and quality["partial"] is True
    assert quality["lines_inspected"] == 6 and quality["lines_total"] == 9


def test_rejections_in_different_units_are_weighted_by_value_not_summed():
    quality = compute_reliability([mixed_po()] * 3, now=NOW)["factors"]["quality"]
    # Inspected: 1000 kg x 10 = 10,000 and 10 L x 500 = 5,000 received; 2 L x 500 = 1,000 rejected.
    # Value-weighted: 1,000 / 15,000 = 6.667% -> 1 - 5 x 0.06667 = 0.6667.
    # (Summing 2 / 1010 units across kg and litres would give 0.198% -> 0.99.)
    assert quality["method"] == "value_weighted"
    assert quality["score"] == round(1 - 5 * (1000 / 15000), 4)


def test_without_prices_mixed_units_fall_back_to_the_mean_line_rate():
    quality = compute_reliability([mixed_po(priced=False)] * 3, now=NOW)["factors"]["quality"]
    # Kg line 0 of 1000 (0%), litre line 2 of 10 (20%): mean 10% -> 1 - 5 x 0.10 = 0.5.
    assert quality["method"] == "line_average"
    assert quality["score"] == 0.5


def test_one_unit_without_prices_stays_quantity_weighted():
    po = mixed_po(priced=False)
    for line in po["lines"]:
        line["unit"] = "pcs"
    quality = compute_reliability([po] * 3, now=NOW)["factors"]["quality"]
    assert quality["method"] == "quantity_weighted"
    assert quality["score"] == round(1 - 5 * (2 / 1010), 4)  # same unit: 2 of 1010 pieces


# --- 3. comparison freshness ---------------------------------------------------------------------------------------


async def _award(api, s):
    return await api.post(f"/api/v1/comparisons/procurement-requests/{s['request']['id']}/award", headers=s["headers"],
                          json={"quotation_id": s["q_shree"]["id"]})


async def test_a_changed_supplier_scorecard_makes_the_comparison_stale(api, db, sourcing):
    await db.suppliers.update_one({"_id": ObjectId(sourcing["shree"]["id"])}, {"$set": {
        "reliability": {"method": "scorecard", "version": 4, "score": 0.2, "status": "rated", "band": "attention"}}})
    response = await _award(api, sourcing)
    assert response.status_code == 409, response.text
    assert "changed since the comparison" in response.json()["error"]["message"]


async def test_changed_default_weights_make_the_comparison_stale(api, sourcing, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "SCORE_WEIGHT_PRICE", settings.SCORE_WEIGHT_PRICE + 0.2)
    assert (await _award(api, sourcing)).status_code == 409


async def test_a_new_scoring_algorithm_version_makes_the_comparison_stale(api, sourcing, monkeypatch):
    from app.services.procurement import comparison

    monkeypatch.setattr(comparison, "COMPARISON_VERSION", comparison.COMPARISON_VERSION + 1)
    assert (await _award(api, sourcing)).status_code == 409


async def test_unchanged_inputs_still_award(api, sourcing):
    assert (await _award(api, sourcing)).status_code == 201


# --- 4. RFQ response matching --------------------------------------------------------------------------------------


def delivered():
    return {"status": "delivered", "on_time": True, "issued_at": NOW - timedelta(days=60), "delivered_at": NOW - timedelta(days=50),
            "lines": [{"quantity": 1}], "pricing": {"total": 1.0}}


def day(n):
    return NOW - timedelta(days=60) + timedelta(days=n)


def rfq(request, n):
    return {"procurement_request_id": request, "sent_at": day(n)}


def emailed(request, n):
    return {"procurement_request_id": request, "created_at": day(n),
            "source": {"metadata": {"channel": "gmail", "received_at": day(n).strftime("%a, %d %b %Y %H:%M:%S +0000")}}}


def uploaded(request, n):
    return {"procurement_request_id": request, "created_at": day(n), "source": {"metadata": {"channel": "upload"}}}


def responsiveness(rfqs, quotations):
    return compute_reliability([delivered()] * 3, rfqs, quotations, now=NOW)["factors"].get("responsiveness")


def test_an_untimed_upload_answers_only_its_own_round():
    # Round 1: sent day 0, answered by a manual upload on day 3 (no email time: not timed, not silence).
    # Round 2: sent day 10, after that answer; nothing since (now is day 60, > 14 days): silence, scores 0.
    factor = responsiveness([rfq("r1", 0), rfq("r1", 10)], [uploaded("r1", 3)])
    assert factor is not None and factor["n"] == 1 and factor["score"] == 0.0
    assert "no reply to 1" in factor["reason"] and "1 replied with no known reply time" in factor["reason"]


def test_mixed_sends_replies_reminders_and_uploads():
    # r1: send 0, reminder 2, email reply 5 -> 5 days from the first send: 1 - (5 - 2) / 12 = 0.75.
    #     send 20, upload 22 -> untimed, not scored.  send 30, nothing -> silent, 0.
    # r2: send 0, email reply 1 -> 1 day: 1.0. An upload on r1 says nothing about r2.
    factor = responsiveness([rfq("r1", 0), rfq("r1", 2), rfq("r1", 20), rfq("r1", 30), rfq("r2", 0)],
                            [emailed("r1", 5), uploaded("r1", 22), emailed("r2", 1)])
    assert factor["n"] == 3
    assert factor["score"] == round((0.75 + 0.0 + 1.0) / 3, 4)


def test_an_upload_before_any_send_answers_nothing():
    # Uploaded on day 0, the request sent on day 5 and never answered: silence, not an untimed reply.
    factor = responsiveness([rfq("r1", 5)], [uploaded("r1", 0)])
    assert factor["n"] == 1 and factor["score"] == 0.0
