"""Stress tests: thousands of generated quotations through validation and the grounding check.

Each case is built from a seed, so a failure names the seed that reproduces it. Clean quotations must raise no error
and no grounding complaint; each kind of injected fault must be caught.
"""
import random

import pytest

from app.schemas.extraction import AIExtractionResult
from app.services.procurement.grounding import grounding_issues
from app.services.procurement.validation import validate_extraction

NAMES = ["PVC pipe 2 inch", "MS plate 10mm", "Brass valve", "LED bulb 9W", "Copier paper A4", "Acrylic color 500ml",
         "Cello tape", "Masking tape", "Steel bolt M12", "Cement OPC 53", "Hand pallet truck", "Safety gloves"]


def money(x: float) -> str:
    """Indian digit grouping, the way an invoice prints it."""
    whole, frac = f"{x:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(groups + [tail]) + "." + frac


def quote(seed: int):
    """(extraction dict, the text it was read from). Totals are consistent and every figure is printed in the text."""
    rng = random.Random(seed)
    items, lines = [], []
    for name in rng.sample(NAMES, rng.randint(1, 8)):
        qty = rng.randint(1, 500)
        rate = round(rng.lognormvariate(5, 1.2), 2)
        total = round(qty * rate, 2)
        items.append({"original_name": name, "quantity": qty, "unit_price": rate, "total_price": total})
        lines.append(f"{name}  {qty}  {money(rate)}  {money(total)}")
    subtotal = round(sum(i["total_price"] for i in items), 2)
    pct = rng.choice([0, 5, 12, 18, 28])
    tax = round(subtotal * pct / 100, 2)
    freight = rng.choice([0.0, round(rng.uniform(100, 3000), 2)])
    grand = round(subtotal + tax + freight, 2)
    text = "\n".join(lines + [f"Subtotal {money(subtotal)}", f"GST {pct}% {money(tax)}"] + ([f"Freight {money(freight)}"] if freight else [])
                     + [f"Grand Total {money(grand)}"])
    commercials = {"subtotal": subtotal, "tax_amount": tax, "tax_percentage": pct, "total_amount": grand}
    if freight:
        commercials["transportation_cost"] = freight
    return {"supplier": {"name": "Balaji Hardware"}, "items": items, "commercials": commercials}, "Balaji Hardware\n" + text


def codes(data: dict, text: str) -> set[str]:
    ext = AIExtractionResult.model_validate(data)
    return {i.code for i in validate_extraction(ext, text).issues}


@pytest.mark.parametrize("seed", range(600))
def test_a_clean_quotation_raises_no_error_and_no_grounding_complaint(seed):
    data, text = quote(seed)
    found = codes(data, text)
    bad = {c for c in found if c.startswith("ungrounded") or c.endswith("mismatch")}
    assert not bad, (seed, bad)


@pytest.mark.parametrize("seed", range(400))
def test_an_inflated_unit_price_with_the_old_line_total_is_caught(seed):
    data, text = quote(10_000 + seed)
    rng = random.Random(seed)
    item = rng.choice(data["items"])
    item["unit_price"] = round(item["unit_price"] * rng.uniform(1.2, 6), 2)
    assert "line_total_mismatch" in codes(data, text), seed


@pytest.mark.parametrize("seed", range(400))
def test_a_changed_grand_total_is_caught(seed):
    data, text = quote(20_000 + seed)
    rng = random.Random(seed)
    data["commercials"]["total_amount"] = round(data["commercials"]["total_amount"] * rng.choice([0.5, 0.9, 1.1, 1.5, 10.0]) + rng.choice([0, 7]), 2)
    found = codes(data, text)
    assert "total_mismatch" in found or "ungrounded_total_amount" in found, seed


@pytest.mark.parametrize("seed", range(400))
def test_an_invented_price_with_a_consistent_line_is_caught_as_not_in_the_document(seed):
    data, text = quote(30_000 + seed)
    rng = random.Random(seed)
    item = rng.choice(data["items"])
    invented = round(rng.uniform(10, 9000), 2) + 0.37  # a figure the text does not contain
    item["unit_price"] = invented
    item["total_price"] = round(item["quantity"] * invented, 2)  # arithmetic stays consistent: only grounding can catch it
    found = codes(data, text)
    assert "ungrounded_unit_price" in found, seed


@pytest.mark.parametrize("seed", range(300))
def test_a_gst_number_the_document_never_printed_is_caught(seed):
    data, text = quote(40_000 + seed)
    data["supplier"]["gst_number"] = "27" + "".join(random.Random(seed).choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5)) + "1234A1Z5"
    assert "ungrounded_gst" in codes(data, text), seed


@pytest.mark.parametrize("seed", range(200))
def test_a_missing_line_item_is_caught_when_it_is_more_than_the_2_percent_tolerance(seed):
    data, text = quote(50_000 + seed)
    if len(data["items"]) < 2:
        pytest.skip("single-line quotation")
    drop = random.Random(seed).randrange(len(data["items"]))
    share = data["items"][drop]["total_price"] / data["commercials"]["subtotal"]
    if share < 0.03:
        pytest.skip("under the tolerance: a line this small is within rounding, a known limit")
    data["items"].pop(drop)
    assert "subtotal_mismatch" in codes(data, text), (seed, share)
