"""Final edge-case audit: award safety, OTIF and inspection evidence, supplier-error attribution, unknown GST basis,
atomic delivery. Written before the fixes and run against the unchanged code first (see
docs/SCORING_FIX_VERIFICATION.md, "Edge-case audit"). Every expected number is derived in the comment beside it.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from app.services.procurement.comparison import build_comparison
from app.services.procurement.reliability import compute_reliability

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def award_url(s):
    return f"/api/v1/comparisons/procurement-requests/{s['request']['id']}/award"


async def award(api, s, quotation="q_shree", **extra):
    return await api.post(award_url(s), headers=s["headers"], json={"quotation_id": s[quotation]["id"], **extra})


async def po_count(db, s):
    return await db.purchase_orders.count_documents({"procurement_request_id": s["request"]["id"]})


# --- 1. award safety -----------------------------------------------------------------------------------------------


async def test_award_without_a_comparison_is_refused(api, db, sourcing):
    await db.comparisons.delete_many({})
    response = await award(api, sourcing)
    assert response.status_code == 409, response.text
    assert "comparison" in response.json()["error"]["message"].lower()
    assert await po_count(db, sourcing) == 0


async def test_award_of_a_quotation_left_out_of_the_comparison_is_refused(api, db, sourcing):
    h = sourcing["headers"]
    compared = await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}", headers=h,
                              json={"include_ai_explanation": False, "quotation_ids": [sourcing["q_shree"]["id"]]})
    assert compared.status_code == 200, compared.text
    response = await award(api, sourcing, "q_apex")
    assert response.status_code == 409, response.text
    assert "not part of the current comparison" in response.json()["error"]["message"]
    assert await po_count(db, sourcing) == 0


async def test_award_from_a_stale_comparison_is_refused_until_recomputed(api, db, sourcing):
    # A price changes after the comparison was run: its ranking no longer describes the quotations.
    await db.quotations.update_one({"_id": ObjectId(sourcing["q_apex"]["id"])},
                                   {"$set": {"effective_data.items.0.unit_price": 50.0}})
    response = await award(api, sourcing)
    assert response.status_code == 409, response.text
    assert "changed since the comparison" in response.json()["error"]["message"]
    assert await po_count(db, sourcing) == 0
    await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}", headers=sourcing["headers"],
                   json={"include_ai_explanation": False})
    assert (await award(api, sourcing)).status_code == 201


async def test_a_quotation_arriving_after_the_comparison_makes_it_stale(api, db, sourcing):
    from app.repositories.quotations import QuotationRepository

    late = {**{k: v for k, v in sourcing["q_apex"].items() if k not in ("id", "organization_id", "created_at", "updated_at")},
            "procurement_request_id": ObjectId(sourcing["request"]["id"]), "supplier_id": ObjectId(sourcing["apex"]["id"])}
    await QuotationRepository(db).create(sourcing["q_apex"]["organization_id"], late)
    assert (await award(api, sourcing)).status_code == 409


async def test_a_second_award_for_the_same_request_is_refused(api, db, sourcing):
    assert (await award(api, sourcing)).status_code == 201
    second = await award(api, sourcing, "q_apex")
    assert second.status_code == 409, second.text
    assert "already has purchase order" in second.json()["error"]["message"]
    assert await po_count(db, sourcing) == 1


async def test_repeating_the_same_award_returns_the_existing_order(api, db, sourcing):
    first = await award(api, sourcing)
    again = await award(api, sourcing)
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert await po_count(db, sourcing) == 1


async def test_concurrent_awards_create_exactly_one_order(api, db, sourcing):
    responses = await asyncio.gather(*(award(api, sourcing, q) for q in ("q_shree", "q_apex") * 4))
    assert await po_count(db, sourcing) == 1
    assert sum(r.status_code == 201 for r in responses) == 1
    assert {r.status_code for r in responses} <= {200, 201, 409}


async def test_a_cancelled_award_frees_the_request_for_a_new_award(api, db, sourcing):
    first = (await award(api, sourcing)).json()
    cancel = await api.post(f"/api/v1/purchase-orders/{first['id']}/cancel", headers=sourcing["headers"],
                            json={"cancelled_by": "buyer"})
    assert cancel.status_code == 200, cancel.text
    assert (await award(api, sourcing, "q_apex")).status_code == 201


async def test_the_agent_path_cannot_create_a_second_order(api, db, sourcing):
    from app.repositories.automation import PurchaseOrderRepository

    assert (await award(api, sourcing)).status_code == 201
    repo = PurchaseOrderRepository(db)
    po = {"procurement_request_id": sourcing["request"]["id"], "quotation_id": sourcing["q_apex"]["id"],
          "lines": [], "status": "draft", "po_number": "PO-X-0001"}
    created, existing = await repo.create_award(sourcing["q_apex"]["organization_id"], po)
    assert created is None and existing["quotation_id"] == sourcing["q_shree"]["id"]
    assert await po_count(db, sourcing) == 1


# --- 2. OTIF evidence coverage ---------------------------------------------------------------------------------------


def order(received=None, ordered=100, rejected=0, on_time=True, inspected=True):
    po = {"status": "delivered", "on_time": on_time, "issued_at": NOW - timedelta(days=20),
          "delivered_at": NOW - timedelta(days=10), "lines": [{"quantity": ordered}], "pricing": {"total": 1000.0}}
    if received is not None:
        line = {"line": 0, "received_quantity": received, "inspected": inspected,
                "rejected_quantity": rejected if inspected else None}
        po["receipt"] = {"lines": [line]}
    return po


def test_partly_receipted_otif_is_partial_and_coverage_counts_the_gap():
    # 2 on time with full receipts, 2 on time with no receipt. Scored on the 2 receipted (both good): 1.0.
    # Evidence: the 2 receipted count fully, the 2 on-time-only count half -> (2 + 0.5 x 2) / 4 = 0.75 of 30%.
    card = compute_reliability([order(100), order(100), order(), order()], now=NOW)
    otif = card["factors"]["on_time_in_full"]
    assert otif["score"] == 1.0 and otif["n"] == 2
    assert otif["partial"] is True and otif["evidence"] == 0.75
    quality = card["factors"]["quality"]  # 2 of 4 delivered orders inspected -> evidence 0.5
    assert quality["partial"] is True and quality["evidence"] == 0.5
    # fulfilment 4 delivered of 4: full evidence 0.15. Coverage = 0.3 x 0.75 + 0.3 x 0.5 + 0.15 = 0.525.
    assert card["coverage"] == 0.525
    assert card["status"] == "provisional"  # under 60% backed by records


def test_missing_receipts_are_neither_successes_nor_failures():
    # One receipted short delivery (80 of 100) and three on time without receipts: 0 of 1, not 3 of 4.
    assert compute_reliability([order(80), order(), order(), order()], now=NOW)["factors"]["on_time_in_full"]["score"] == 0.0
    # One receipted good delivery and three without receipts: 1 of 1, not 1 of 4.
    assert compute_reliability([order(100), order(), order(), order()], now=NOW)["factors"]["on_time_in_full"]["score"] == 1.0


def test_fully_receipted_otif_is_not_partial():
    card = compute_reliability([order(100)] * 5, now=NOW)
    assert card["factors"]["on_time_in_full"]["partial"] is False
    assert card["factors"]["on_time_in_full"]["evidence"] == 1.0


# --- 3. quality inspection -----------------------------------------------------------------------------------------


def test_receipts_not_yet_inspected_give_no_quality_evidence():
    card = compute_reliability([order(100, inspected=False)] * 5, now=NOW)
    assert "quality" not in card["factors"]
    # In full is judged on what arrived: 100 received of 100 ordered.
    assert card["factors"]["on_time_in_full"]["score"] == 1.0


def test_inspected_with_zero_rejected_is_real_quality_evidence():
    card = compute_reliability([order(100, rejected=0, inspected=True)] * 5, now=NOW)
    assert card["factors"]["quality"]["score"] == 1.0 and card["factors"]["quality"]["n"] == 5


def test_legacy_receipts_with_a_defaulted_zero_are_not_inspection_evidence():
    # Stored before inspection was recorded: no "inspected" flag. A zero there may be the old default.
    legacy_zero = order(100)
    legacy_zero["receipt"]["lines"][0].pop("inspected")
    legacy_rejected = order(100, rejected=4)
    legacy_rejected["receipt"]["lines"][0].pop("inspected")  # a rejection can only come from an inspection
    card = compute_reliability([legacy_zero] * 4 + [legacy_rejected], now=NOW)
    assert card["factors"]["quality"]["n"] == 1
    assert card["factors"]["quality"]["score"] == round(1 - 5 * 0.04, 4)  # 4 of 100 rejected = 4% -> 0.8


async def _issued(api, s):
    created = await award(api, s)
    assert created.status_code == 201, created.text
    po = created.json()
    for action in ("approve", "issue"):
        assert (await api.post(f"/api/v1/purchase-orders/{po['id']}/{action}", headers=s["headers"])).status_code == 200
    return po


async def test_api_receipt_without_a_rejected_quantity_is_recorded_as_not_inspected(api, sourcing):
    po = await _issued(api, sourcing)
    response = await api.post(f"/api/v1/purchase-orders/{po['id']}/deliver", headers=sourcing["headers"], json={
        "receipt": {"lines": [{"line": 0, "received_quantity": 100}, {"line": 1, "received_quantity": 500, "rejected_quantity": 0}]}})
    assert response.status_code == 200, response.text
    lines = response.json()["receipt"]["lines"]
    assert (lines[0]["inspected"], lines[0]["rejected_quantity"], lines[0]["accepted_quantity"]) == (False, None, None)
    assert (lines[1]["inspected"], lines[1]["rejected_quantity"], lines[1]["accepted_quantity"]) == (True, 0, 500)


# --- 4. supplier error attribution ---------------------------------------------------------------------------------

REQUEST = {"id": "req", "title": "t", "currency": "INR", "items": [{"item_id": "i1", "name": "A4", "quantity": 10}]}
TOTAL_ISSUE = {"field": "pricing.total_amount", "code": "total_mismatch", "severity": "warning",
               "message": "Total does not match subtotal plus GST."}
LINE_ISSUE = {"field": "items.0", "code": "line_total_mismatch", "severity": "warning", "message": "Line total does not match."}


def quote(qid, *, total=1180.0, landed=None, tax_pct=18, issues=(), corrections=(), confirmations=(), subtotal=1000.0):
    return {"id": qid, "supplier_name": qid, "processing_status": "COMPLETED",
            "effective_data": {"items": [{"line_id": "L1", "quantity": 10, "unit_price": subtotal / 10, "total_price": subtotal}],
                               "pricing": {"currency": "INR", "subtotal": subtotal, "total_amount": total,
                                           "landed_total": landed if landed is not None else total, "tax_percentage": tax_pct},
                               "delivery": {"delivery_days": 7}, "payment_terms": {"payment_days": 30}},
            "match_result": {"matched_count": 1, "coverage": 1.0},
            "validation": {"issues": list(issues)}, "user_corrections": list(corrections),
            "confirmed_issues": list(confirmations)}


def row(quotation):
    return build_comparison(REQUEST, [quotation]).suppliers[0]


def test_an_unrelated_correction_does_not_confirm_arithmetic_errors():
    flagged = row(quote("a", issues=[TOTAL_ISSUE, LINE_ISSUE], corrections=[{"path": "supplier.name"}]))
    assert flagged.confirmed_supplier_errors == [] and flagged.unverified_issues == 2


def test_only_the_explicitly_confirmed_field_is_the_suppliers_error():
    confirmed = row(quote("a", issues=[TOTAL_ISSUE, LINE_ISSUE],
                          confirmations=[{"field": "pricing.total_amount", "code": "total_mismatch",
                                          "confirmed_at": NOW}]))
    assert confirmed.confirmed_supplier_errors == ["Total does not match subtotal plus GST."]
    assert confirmed.unverified_issues == 1  # the line total was never confirmed


def test_correcting_the_field_after_confirming_withdraws_the_confirmation():
    later = row(quote("a", issues=[TOTAL_ISSUE],
                      confirmations=[{"field": "pricing.total_amount", "code": "total_mismatch", "confirmed_at": NOW}],
                      corrections=[{"path": "pricing.total_amount", "corrected_at": NOW + timedelta(hours=1)}]))
    assert later.confirmed_supplier_errors == []


async def test_confirming_a_supplier_error_through_the_api(api, db, sourcing):
    h, qid = sourcing["headers"], sourcing["q_shree"]["id"]
    await db.quotations.update_one({"_id": ObjectId(qid)}, {"$set": {"validation.issues": [TOTAL_ISSUE]}})
    url = f"/api/v1/quotations/{qid}/issue-confirmations"
    assert (await api.post(url, headers=h, json={"field": "pricing.subtotal", "code": "subtotal_mismatch"})).status_code == 409
    assert (await api.post(url, headers=h, json={"field": "pricing.total_amount", "code": "total_mismatch"})).status_code == 200
    compared = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}", headers=h,
                               json={"include_ai_explanation": False})).json()
    shree = {r["supplier_name"]: r for r in compared["suppliers"]}["Shree Steel"]
    assert shree["confirmed_supplier_errors"] == ["Total does not match subtotal plus GST."]


# --- 5. GST comparison with every basis unknown -------------------------------------------------------------------


def test_when_no_quotation_shows_its_gst_basis_raw_totals_are_not_ranked():
    # Net 1000 / total 1100 and net 900 / total 1000, no GST rate or amount: neither total reconciles, basis unknown.
    result = build_comparison(REQUEST, [quote("a", total=1100, tax_pct=None),
                                        quote("b", total=1000, tax_pct=None, subtotal=900)])
    by_name = {s.supplier_name: s for s in result.suppliers}
    for supplier in by_name.values():
        price = next(c for c in supplier.criteria if c.criterion == "price")
        assert price.data_available is False and price.score == 0.5      # neutral: the totals are not comparable
        assert price.raw_value is None
        assert supplier.requires_review is True
        assert any("includes GST" in reason for reason in supplier.review_reasons)
    assert result.recommended_quotation_id is None
    assert any("not ranked on price" in w for w in result.warnings)
    # The quoted totals are still shown for the person reviewing.
    assert by_name["a"].landed_cost == 1100 and by_name["b"].landed_cost == 1000


# --- 6. atomic delivery ----------------------------------------------------------------------------------------------


async def test_an_invalid_receipt_leaves_the_order_undelivered(api, db, sourcing):
    po = await _issued(api, sourcing)
    url = f"/api/v1/purchase-orders/{po['id']}/deliver"
    bad = [
        {"lines": [{"line": 0, "received_quantity": 100, "rejected_quantity": 0},
                   {"line": 0, "received_quantity": 500, "rejected_quantity": 0}]},          # line 0 twice
        {"lines": [{"line": 0, "received_quantity": 100, "rejected_quantity": 0}]},         # line 1 missing
        {"lines": [{"line": 0, "received_quantity": 5, "rejected_quantity": 6},
                   {"line": 1, "received_quantity": 500, "rejected_quantity": 0}]},         # more rejected than received
    ]
    for receipt in bad:
        response = await api.post(url, headers=sourcing["headers"], json={"receipt": receipt})
        assert response.status_code == 409, receipt
        stored = await db.purchase_orders.find_one({"_id": ObjectId(po["id"])})
        assert stored["status"] == "issued" and "receipt" not in stored and "delivered_at" not in stored
        assert [h["action"] for h in stored["history"]].count("deliver") == 0


async def test_delivery_and_receipt_are_saved_together(api, db, sourcing):
    po = await _issued(api, sourcing)
    response = await api.post(f"/api/v1/purchase-orders/{po['id']}/deliver", headers=sourcing["headers"], json={
        "receipt": {"lines": [{"line": 0, "received_quantity": 100, "rejected_quantity": 0},
                              {"line": 1, "received_quantity": 500, "rejected_quantity": 0}]}})
    assert response.status_code == 200, response.text
    stored = await db.purchase_orders.find_one({"_id": ObjectId(po["id"])})
    assert stored["status"] == "delivered" and stored["receipt"]["in_full"] is True
    actions = [h["action"] for h in stored["history"]]
    assert actions[-2:] == ["deliver", "receipt_recorded"]


async def test_concurrent_deliveries_are_recorded_once(api, db, sourcing):
    po = await _issued(api, sourcing)
    url = f"/api/v1/purchase-orders/{po['id']}/deliver"
    responses = await asyncio.gather(*(api.post(url, headers=sourcing["headers"]) for _ in range(4)))
    assert sorted(r.status_code for r in responses) == [200, 409, 409, 409]
    stored = await db.purchase_orders.find_one({"_id": ObjectId(po["id"])})
    assert [h["action"] for h in stored["history"]].count("deliver") == 1
