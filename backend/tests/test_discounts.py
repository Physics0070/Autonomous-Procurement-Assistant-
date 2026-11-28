"""Discounts: read as printed, reconciled deterministically, and carried into what is compared and ordered."""
from app.schemas.extraction import AIExtractionResult
from app.services.automation.purchase_orders import build_purchase_order
from app.services.procurement.normalizer_service import normalize_quotation
from app.services.procurement.validation import line_net_total, quotation_discount, validate_extraction


def _quote(items, **commercials):
    return AIExtractionResult.model_validate({"supplier": {"name": "Zorvik"}, "items": items, "commercials": commercials})


def test_discount_arithmetic():
    assert line_net_total(10, 100, discount_percentage=5) == 950
    assert line_net_total(10, 100, discount_amount=50, discount_percentage=99) == 950  # a printed amount wins
    assert line_net_total(None, 100, 5) is None
    assert quotation_discount(868062.0, None, 5) == 43403.1
    assert quotation_discount(100.0, -10.0, None) == 10.0  # "Less discount (-10)" is still a 10 discount
    assert quotation_discount(100.0, None, None) == 0.0


def test_a_line_discount_reconciles_and_is_not_a_mismatch():
    q = _quote([{"original_name": "Cable", "quantity": 10, "unit_price": 100, "discount_percentage": 5, "total_price": 950}])
    assert not [i for i in validate_extraction(q).issues if i.code == "line_total_mismatch"]


def test_a_wrong_line_amount_is_still_caught_with_a_discount():
    q = _quote([{"original_name": "Cable", "quantity": 10, "unit_price": 100, "discount_percentage": 5, "total_price": 1000}])
    assert validate_extraction(q).requires_review


def test_a_quotation_discount_reconciles_before_tax():
    # benchmark Q006: 868,062 less 5% (43,403.10) + IGST 148,501.60 + freight 350 = 973,510.50
    q = _quote([{"original_name": "Pump", "quantity": 1, "unit_price": 868062, "total_price": 868062}], subtotal=868062,
               discount_amount=43403.1, discount_percentage=5, tax_amount=148501.6, transportation_cost=350, total_amount=973510.5)
    assert not validate_extraction(q).requires_review
    unread = _quote([{"original_name": "Pump", "quantity": 1, "unit_price": 868062, "total_price": 868062}], subtotal=868062,
                    tax_amount=148501.6, transportation_cost=350, total_amount=973510.5)
    assert validate_extraction(unread).requires_review  # without the discount it does not add up, so a person looks


def test_normalised_prices_are_what_is_actually_paid():
    n = normalize_quotation(_quote([{"original_name": "Cable", "quantity": 10, "unit_price": 100, "discount_percentage": 5,
                                     "total_price": 950}], subtotal=950, discount_amount=95, tax_percentage=18))
    item = n.items[0]
    assert item.unit_price == 95 and item.list_price == 100 and item.computed_total == 950
    assert n.pricing.discount_amount == 95
    assert n.pricing.landed_total == round(950 - 95 + 855 * 0.18, 2)  # GST charged on the discounted value


def test_the_purchase_order_takes_the_discount_off_before_gst():
    quotation = {"id": "q1", "effective_data": {
        "items": [{"line_id": "line-1", "unit_price": 95, "tax_percentage": 18}],
        "pricing": {"subtotal": 1000, "discount_amount": 100, "discount_percentage": 10, "currency": "INR"}},
        "match_result": {"matches": [{"request_item_id": "r1", "matched": True, "quotation_line_id": "line-1"}]}}
    request = {"id": "req", "items": [{"item_id": "r1", "name": "Cable", "quantity": 20}]}
    po = build_purchase_order(request, quotation, None, {"gst_number": None})
    p = po["pricing"]
    # A 10% discount applies to whatever is ordered. (A fixed amount is not scaled: tests/test_scoring_followup.py.)
    assert p["subtotal"] == 1900 and p["discount"] == 190 and p["discount_type"] == "percentage"
    assert sum(t["amount"] for t in p["taxes"]) == round(1710 * 0.18, 2)
    assert p["total"] == round(1900 - 190 + 1710 * 0.18, 2)


def test_without_a_discount_the_purchase_order_is_unchanged():
    quotation = {"id": "q1", "effective_data": {"items": [{"line_id": "line-1", "unit_price": 100, "tax_percentage": 18}],
                                                 "pricing": {"subtotal": 1000}},
                 "match_result": {"matches": [{"request_item_id": "r1", "matched": True, "quotation_line_id": "line-1"}]}}
    po = build_purchase_order({"id": "req", "items": [{"item_id": "r1", "name": "Cable", "quantity": 10}]}, quotation, None, {})
    assert po["pricing"]["discount"] == 0 and po["pricing"]["total"] == 1180
