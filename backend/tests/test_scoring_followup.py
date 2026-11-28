"""Follow-up scoring and purchase-order defects, written before their fixes (see docs/SCORING_FIX_VERIFICATION.md).

Every expected number is derived in the comment beside it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.errors import ConflictError
from app.services.automation import purchase_orders as pos
from app.services.automation.purchase_orders import build_purchase_order, transition
from app.services.procurement.comparison import build_comparison, tax_basis
from app.services.procurement.reliability import compute_reliability, invoice_check

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def delivered(received=(100,), rejected=(0,), ordered=(100,), invoice=None, total=1000.0):
    return {"status": "delivered", "on_time": True, "issued_at": NOW - timedelta(days=20), "delivered_at": NOW - timedelta(days=10),
            "lines": [{"quantity": q} for q in ordered], "pricing": {"total": total},
            "receipt": {"lines": [{"line": i, "received_quantity": r, "rejected_quantity": j}
                                  for i, (r, j) in enumerate(zip(received, rejected))], "invoice_amount": invoice}}


# --- reliability --------------------------------------------------------------------------------------------------


def test_one_rejected_unit_out_of_100():
    card = compute_reliability([delivered(rejected=(1,))] * 3, now=NOW)
    assert card["factors"]["on_time_in_full"]["score"] == 0.0     # accepted 99 < 100 ordered: not in full
    assert card["factors"]["quality"]["score"] == 0.95            # 3 of 300 = 1% -> 1 - 5 x 0.01
    assert "1.0% of quantity rejected at inspection (3 of 300, 3 orders)" == card["factors"]["quality"]["reason"]


def test_zero_invoice_amount_is_not_scored_as_underbilling():
    assert invoice_check(delivered(invoice=0)) == "invalid"
    assert "commercial" not in compute_reliability([delivered(invoice=0)] * 3, now=NOW)["factors"]


def emailed(request, day):
    when = NOW - timedelta(days=40) + timedelta(days=day)
    return {"procurement_request_id": request,
            "source": {"metadata": {"channel": "gmail", "received_at": when.strftime("%a, %d %b %Y %H:%M:%S +0000")}}}


def rfq(request, day):
    return {"procurement_request_id": request, "sent_at": NOW - timedelta(days=40) + timedelta(days=day)}


def test_each_rfq_round_is_timed_against_its_own_reply():
    # Round 1: sent day 0, answered day 3. Round 2 (new request round after that reply): sent day 20, answered day 21.
    factor = compute_reliability([delivered()] * 3, [rfq("r1", 0), rfq("r1", 20)], [emailed("r1", 3), emailed("r1", 21)],
                                 now=NOW)["factors"]["responsiveness"]
    assert factor["n"] == 2
    assert factor["score"] == round((1 - (3 - 2) / 12 + 1.0) / 2, 4)  # 3 days -> 0.9167; 1 day -> 1.0


def test_a_reminder_before_any_reply_does_not_restart_the_clock():
    # Sent day 0, reminder day 5, reply day 6: one round, 6 days from the first send -> 1 - (6 - 2) / 12.
    factor = compute_reliability([delivered()] * 3, [rfq("r1", 0), rfq("r1", 5)], [emailed("r1", 6)],
                                 now=NOW)["factors"]["responsiveness"]
    assert factor["n"] == 1 and factor["score"] == round(1 - 4 / 12, 4)


# --- comparison --------------------------------------------------------------------------------------------------

REQUEST = {"id": "req", "title": "t", "currency": "INR", "items": [{"item_id": "i1", "name": "A4", "quantity": 10}]}


def quote(qid, *, price=100.0, qty=10, total=None, tax_pct=None, text="", delivery=7, payment=30, discount_amount=None,
          discount_pct=None, currency="INR", gross=None):
    subtotal = gross if gross is not None else price * qty
    return {"id": qid, "supplier_name": qid, "processing_status": "COMPLETED", "supplier_id": None,
            "raw_content": {"raw_text": text},
            "effective_data": {"items": [{"line_id": "L1", "quantity": qty, "unit_price": price, "total_price": price * qty,
                                          "tax_percentage": tax_pct}],
                               "pricing": {"currency": currency, "subtotal": subtotal, "total_amount": total, "landed_total": total,
                                           "tax_percentage": tax_pct, "discount_amount": discount_amount,
                                           "discount_percentage": discount_pct},
                               "delivery": {"delivery_days": delivery}, "payment_terms": {"payment_days": payment}},
            "match_result": {"matched_count": 1, "coverage": 1.0,
                             "matches": [{"request_item_id": "i1", "quotation_line_id": "L1", "matched": True, "unit_price": price}]}}


def criterion(supplier, name):
    return next(c for c in supplier.criteria if c.criterion == name)


def test_a_single_quotation_gets_no_perfect_relative_scores():
    only = build_comparison(REQUEST, [quote("only", total=1180, tax_pct=18)]).suppliers[0]
    for name in ("price", "delivery", "payment"):
        assert criterion(only, name).score == 0.5, name
        assert any("nothing to compare" in d for d in criterion(only, name).deductions), name


def test_tied_quotations_get_no_perfect_relative_scores():
    result = build_comparison(REQUEST, [quote("a", total=1180, tax_pct=18), quote("b", total=1180, tax_pct=18)])
    assert {criterion(s, "price").score for s in result.suppliers} == {0.5}
    assert any("all the same" in d for d in criterion(result.suppliers[0], "price").deductions)


def test_gst_wording_decides_when_the_figures_cannot():
    inclusive = quote("x", total=1000, tax_pct=18, text="Rates are inclusive of GST.")["effective_data"]
    assert tax_basis(inclusive, "Rates are inclusive of GST.")[:2] == ("inclusive", 1000)   # not 1,000 + 18%
    extra = quote("y", total=1000, text="GST extra as applicable")["effective_data"]
    assert tax_basis(extra, "GST extra as applicable")[0] == "exclusive"                   # rate unknown
    assert tax_basis(extra, "GST extra as applicable")[1] is None                          # so no comparable price
    assert tax_basis(quote("z", total=1000, tax_pct=18)["effective_data"], "")[:2] == ("exclusive", 1180.0)


def test_comparison_reads_the_document_wording():
    result = build_comparison(REQUEST, [quote("incl", total=1100, tax_pct=18, price=110, text="Prices incl. GST"),
                                        quote("extra", total=1000, tax_pct=18, text="GST 18% extra")])
    rows = {s.supplier_name: s for s in result.suppliers}
    assert rows["incl"].comparable_price == 1100 and rows["extra"].comparable_price == 1180.0
    assert criterion(rows["incl"], "price").score == 1.0


# --- purchase orders ---------------------------------------------------------------------------------------------

BUYER = {"name": "Buyer", "gst_number": "27AABCV1234K1Z5"}
SUPPLIER = {"name": "Seller", "gst_number": "27AABCS1429B1ZQ"}


def request(qty=10):
    return {"id": "req", "currency": "INR", "items": [{"item_id": "i1", "name": "A4", "quantity": qty, "unit": "ream"}]}


def test_gst_inclusive_unit_prices_are_not_taxed_twice():
    q = quote("incl", price=118, total=1180, tax_pct=18, text="All rates inclusive of GST")
    po = build_purchase_order(request(), q, SUPPLIER, BUYER)
    assert po["lines"][0]["unit_price"] == 100.0 and po["pricing"]["subtotal"] == 1000.0   # 118 / 1.18
    assert sum(t["amount"] for t in po["pricing"]["taxes"]) == 180.0 and po["pricing"]["total"] == 1180.0
    assert any("inclusive of GST" in w for w in po["warnings"])
    assert pos.reconcile(po) == []


def test_unknown_gst_treatment_is_flagged_on_the_po():
    po = build_purchase_order(request(), quote("u", total=1000), SUPPLIER, BUYER)
    assert any("include GST" in w for w in po["warnings"])


def test_percentage_discount_scales_with_quantity():
    # 10% quoted; ordering 20 instead of 10: subtotal 2,000, discount 200.
    po = build_purchase_order(request(20), quote("p", total=1062, tax_pct=18, discount_pct=10, discount_amount=100), SUPPLIER, BUYER)
    assert po["pricing"]["discount"] == 200.0 and po["pricing"]["discount_type"] == "percentage"


def test_fixed_discount_is_not_scaled_when_quantities_change():
    same = build_purchase_order(request(10), quote("f", total=1062, tax_pct=18, discount_amount=100), SUPPLIER, BUYER)
    assert same["pricing"]["discount"] == 100.0 and same["pricing"]["discount_type"] == "fixed"
    more = build_purchase_order(request(20), quote("f", total=1062, tax_pct=18, discount_amount=100), SUPPLIER, BUYER)
    assert more["pricing"]["discount"] == 0.0
    assert any("fixed discount" in w.lower() for w in more["warnings"])


def test_ordering_a_different_quantity_than_quoted_is_flagged_for_tiered_rates():
    po = build_purchase_order(request(50), quote("t", total=1180, tax_pct=18), SUPPLIER, BUYER)
    assert any("quoted for 10" in w and "ordering 50" in w for w in po["warnings"])


def test_po_reconciles_to_the_paisa():
    # 3 x 33.333 = 99.999 -> 100.00; intra-state 18% -> CGST 9.00 + SGST 9.00; freight 0.
    q = quote("r", price=33.333, qty=3, total=118, tax_pct=18)
    po = build_purchase_order(request(3), q, SUPPLIER, BUYER)
    p = po["pricing"]
    assert pos.reconcile(po) == []
    assert round(p["subtotal"] - p["discount"] + sum(t["amount"] for t in p["taxes"]) + p["freight"], 2) == p["total"]
    assert round(sum(line["line_total"] for line in po["lines"]), 2) == p["subtotal"]


@pytest.mark.parametrize("price", [float("nan"), float("inf"), -5.0, 0.0])
def test_invalid_prices_never_reach_a_po_line(price):
    po = build_purchase_order(request(), quote("bad", price=price, total=None), SUPPLIER, BUYER)
    assert po["lines"] == [] and any("invalid" in w for w in po["warnings"])


def test_a_po_that_does_not_reconcile_cannot_be_approved():
    po = build_purchase_order(request(), quote("ok", total=1180, tax_pct=18), SUPPLIER, BUYER)
    po["status"] = "draft"
    po["pricing"]["total"] += 50  # tampered or corrupted
    with pytest.raises(ConflictError):
        transition(po, "approve", "user")
    po["pricing"]["total"] = float("nan")
    with pytest.raises(ConflictError):
        transition(po, "approve", "user")


async def test_zero_invoice_amount_is_refused_by_the_api(api, sourcing):
    h = sourcing["headers"]
    po = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/award", headers=h,
                         json={"quotation_id": sourcing["q_shree"]["id"]})).json()
    for action in ("approve", "issue", "deliver"):
        assert (await api.post(f"/api/v1/purchase-orders/{po['id']}/{action}", headers=h)).status_code == 200
    lines = [{"line": i, "received_quantity": line["quantity"]} for i, line in enumerate(po["lines"])]
    response = await api.put(f"/api/v1/purchase-orders/{po['id']}/receipt", headers=h, json={"lines": lines, "invoice_amount": 0})
    assert response.status_code == 422
