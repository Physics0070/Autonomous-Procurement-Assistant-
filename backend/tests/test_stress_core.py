"""Stress tests for the rest of the pure logic: second-reader reconciliation, price anomaly, GST, parsing,
comparison ranking, search and forecasting. Seeded, so a failure names the seed that reproduces it."""
import json
import random

import numpy as np
import pandas as pd
import pytest

from app.core.gstin import check_digit, has_valid_check_digit, is_valid_gstin, state_code
from app.schemas.extraction import AIExtractionResult, coerce_number
from app.services.agents.retrieval import build_chunks, search
from app.services.automation.purchase_orders import tax_split
from app.services.documents.ai_extraction import parse_json_response
from app.services.documents.second_reader import compare_readings, reconcile_readings
from app.services.procurement.comparison import build_comparison
from ml.anomaly import assess_price
from ml.forecast import forecast_demand, monthly_series


# ---------------------------------------------------------------- second reader
def _reading(rng, total=None):
    items = [{"original_name": f"Item {k} {rng.choice(['pipe', 'plate', 'valve', 'tape'])}", "quantity": rng.randint(1, 50),
              "unit_price": round(rng.uniform(5, 900), 2)} for k in range(rng.randint(1, 6))]
    for i in items:
        i["total_price"] = round(i["quantity"] * i["unit_price"], 2)
    return AIExtractionResult.model_validate({"items": items, "commercials": {"total_amount": total or round(sum(i["total_price"] for i in items), 2)}})


@pytest.mark.parametrize("seed", range(500))
def test_a_trailing_digit_on_a_whole_amount_is_always_corrected_from_the_image(seed):
    rng = random.Random(seed)
    image = _reading(rng)
    for i in image.items:  # whole-rupee amounts: what handwriting like 4800/- produces
        i.total_price = float(rng.randint(100, 90000))
    text = image.model_copy(deep=True)
    target = rng.randrange(len(text.items))
    original = text.items[target].total_price
    text.items[target].total_price = original * 10 + rng.randint(0, 9)
    kept, notes, adopted = reconcile_readings(text, image)
    assert kept.items[target].total_price == original and notes and not adopted, seed


@pytest.mark.parametrize("seed", range(500))
def test_a_real_difference_is_never_auto_corrected(seed):
    rng = random.Random(seed)
    image = _reading(rng)
    text = image.model_copy(deep=True)
    i = rng.randrange(len(text.items))
    text.items[i].unit_price = round(image.items[i].unit_price * rng.uniform(1.05, 1.9), 2)  # nowhere near x10 + digit
    kept, notes, _ = reconcile_readings(text, image)
    assert kept.items[i].unit_price == text.items[i].unit_price, seed
    assert any(x.field == f"items.{i}.unit_price" for x in compare_readings(kept, image)), seed


@pytest.mark.parametrize("seed", range(200))
def test_identical_readings_never_disagree(seed):
    reading = _reading(random.Random(seed))
    assert compare_readings(reading, reading.model_copy(deep=True)) == []


# ---------------------------------------------------------------- price anomaly
def _history(seed):
    rng = np.random.default_rng(seed)
    sigma = float(rng.uniform(0.03, 0.3))
    center = float(rng.uniform(5, 5000))
    n = int(rng.integers(8, 60))
    return center * np.exp(rng.normal(0, sigma, n)), rng


@pytest.mark.parametrize("seed", range(300))
def test_an_ordinary_price_is_not_flagged(seed):
    history, _ = _history(seed)
    median, spread = float(np.median(history)), float(np.std(np.log(history), ddof=1))
    price = median * np.exp(1.2 * spread)  # a little over one standard deviation out: ordinary
    assert assess_price(price, history)["status"] == "NORMAL", seed


@pytest.mark.parametrize("seed", range(300))
def test_a_price_far_outside_the_usual_range_is_always_flagged(seed):
    history, rng = _history(10_000 + seed)
    median, spread = float(np.median(history)), float(np.std(np.log(history), ddof=1))
    z = float(rng.uniform(6, 20)) * (1 if rng.random() < 0.5 else -1)
    result = assess_price(median * np.exp(z * spread), history)
    assert result["status"] in {"POSSIBLE_ANOMALY", "HIGH_ANOMALY"}, (seed, z)


@pytest.mark.parametrize("seed", range(100))
def test_the_price_detector_is_deterministic(seed):
    history, rng = _history(20_000 + seed)
    price = float(np.median(history) * rng.uniform(0.5, 2.0))
    assert assess_price(price, history) == assess_price(price, history)


# ---------------------------------------------------------------- GST
def _gstin(rng, state="27"):
    body = state + "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(5)) + "".join(rng.choice("0123456789") for _ in range(4)) \
        + rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ") + "1Z"
    return body + check_digit(body)


@pytest.mark.parametrize("seed", range(300))
def test_a_generated_gstin_with_its_check_digit_is_valid(seed):
    assert has_valid_check_digit(_gstin(random.Random(seed))), seed


@pytest.mark.parametrize("seed", range(300))
def test_changing_any_one_character_of_a_gstin_breaks_the_check(seed):
    rng = random.Random(seed)
    good = _gstin(rng)
    pos = rng.randrange(15)
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    bad = good[:pos] + rng.choice([c for c in alphabet if c != good[pos]]) + good[pos + 1:]
    assert not has_valid_check_digit(bad), (good, bad)


@pytest.mark.parametrize("seed", range(500))
def test_tax_is_split_correctly_and_always_adds_up(seed):
    rng = random.Random(seed)
    rates = {float(r): round(rng.uniform(10, 500000), 2) for r in rng.sample([5, 12, 18, 28], rng.randint(1, 4))}
    same = rng.random() < 0.5
    buyer = _gstin(rng, "27")
    supplier = _gstin(rng, "27" if same else "29")
    lines = tax_split(rates, buyer, supplier)
    names = {l["name"] for l in lines}
    assert names == ({"CGST", "SGST"} if same else {"IGST"}), seed
    for rate, taxable in rates.items():
        expected = round(taxable * rate / 100, 2)
        got = round(sum(l["amount"] for l in lines if abs(l["rate"] * (2 if same else 1) - rate) < 1e-9), 2)
        assert abs(got - expected) <= 0.011, (seed, rate, got, expected)


@pytest.mark.parametrize("seed", range(100))
def test_an_unknown_gstin_gives_plain_gst_not_a_guess(seed):
    rng = random.Random(seed)
    lines = tax_split({18.0: round(rng.uniform(100, 9000), 2)}, None, _gstin(rng))
    assert {l["name"] for l in lines} == {"GST"}


# ---------------------------------------------------------------- parsing never raises
@pytest.mark.parametrize("seed", range(500))
def test_the_json_reader_never_raises_on_garbage(seed):
    rng = random.Random(seed)
    junk = "".join(rng.choice('{}[]",:\\ abcXYZ0123456789\n`') for _ in range(rng.randint(0, 200)))
    data, error = parse_json_response(junk)
    assert (data is None) == (error is not None) and (data is None or isinstance(data, dict)), junk


@pytest.mark.parametrize("seed", range(300))
def test_well_formed_json_in_fences_or_with_prose_is_read(seed):
    rng = random.Random(seed)
    payload = {"items": [{"original_name": "x", "quantity": rng.randint(1, 9)}]}
    body = json.dumps(payload)
    wrapped = rng.choice([body, f"```json\n{body}\n```", f"Here is the result:\n{body}\nHope that helps.", f"```\n{body}\n```"])
    data, error = parse_json_response(wrapped)
    assert data == payload and error is None, wrapped


@pytest.mark.parametrize("seed", range(300))
def test_numbers_written_the_indian_way_are_read_exactly(seed):
    rng = random.Random(seed)
    value = round(rng.uniform(1, 9_999_999), 2)
    whole, frac = f"{value:.2f}".split(".")
    head, tail, groups = whole[:-3], whole[-3:], []
    while head:
        groups.insert(0, head[-2:])
        head = head[:-2]
    text = ",".join(groups + [tail]) + "." + frac
    assert coerce_number(rng.choice(["₹", "Rs. ", "INR ", ""]) + text + rng.choice(["", "/-"])) == value, text


@pytest.mark.parametrize("seed", range(300))
def test_unreadable_amounts_become_none_not_a_guess(seed):
    rng = random.Random(seed)
    junk = "".join(rng.choice("abcxyz ~!@#?") for _ in range(rng.randint(1, 12)))
    assert coerce_number(junk) is None


# ---------------------------------------------------------------- comparison ranking
def _quote(rng, name, total, days):
    return {"id": name, "supplier_name": name, "processing_status": "COMPLETED", "match_result": {"matched_count": 3, "coverage": 1.0},
            "effective_data": {"pricing": {"total_amount": total, "tax_amount": total * 0.15, "currency": "INR"},
                               "delivery": {"delivery_days": days}, "payment_terms": {"payment_days": 30}, "items": []}}


@pytest.mark.parametrize("seed", range(300))
def test_with_everything_else_equal_the_cheapest_supplier_ranks_first(seed):
    rng = random.Random(seed)
    totals = rng.sample(range(10_000, 90_000, 37), rng.randint(2, 6))
    quotes = [_quote(rng, f"S{i}", float(t), 10) for i, t in enumerate(totals)]
    result = build_comparison({"id": "r", "title": "t", "items": [{"name": "a"}]}, quotes)
    best = min(range(len(totals)), key=lambda i: totals[i])
    top = min(result.suppliers, key=lambda s: s.rank)
    assert top.supplier_name == f"S{best}", (seed, totals)
    assert sorted(s.rank for s in result.suppliers) == list(range(1, len(totals) + 1))


@pytest.mark.parametrize("seed", range(200))
def test_scaling_every_price_by_the_same_factor_keeps_the_ranking(seed):
    rng = random.Random(seed)
    base = [(rng.randint(10_000, 90_000), rng.randint(3, 30)) for _ in range(rng.randint(2, 6))]
    def ranking(scale):
        qs = [_quote(rng, f"S{i}", float(t * scale), d) for i, (t, d) in enumerate(base)]
        r = build_comparison({"id": "r", "title": "t", "items": [{"name": "a"}]}, qs)
        return [s.supplier_name for s in sorted(r.suppliers, key=lambda s: s.rank)]
    assert ranking(1) == ranking(rng.choice([2, 7, 0.5, 100])), seed


@pytest.mark.parametrize("seed", range(200))
def test_scores_stay_between_zero_and_one(seed):
    rng = random.Random(seed)
    quotes = [_quote(rng, f"S{i}", float(rng.randint(500, 900_000)), rng.randint(0, 120)) for i in range(rng.randint(1, 7))]
    for s in build_comparison({"id": "r", "title": "t", "items": [{"name": "a"}]}, quotes).suppliers:
        assert 0.0 <= s.overall_score <= 1.0, (seed, s.overall_score)


# ---------------------------------------------------------------- search
WORDS = ["flange", "gasket", "impeller", "turbine", "ratchet", "caliper", "solder", "rivet", "bearing", "sprocket", "ferrule", "grommet"]


@pytest.mark.parametrize("seed", range(200))
def test_a_distinctive_word_finds_its_own_record(seed):
    rng = random.Random(seed)
    target = rng.choice(WORDS)
    quotes = [{"id": f"q{i}", "supplier_name": f"S{i}", "effective_data": {"items": [{"original_name": f"{w} 12mm", "quantity": 1, "unit_price": 10.0}]}}
              for i, w in enumerate(WORDS)]
    hits = search(build_chunks(quotes, []), f"who quoted {target}")
    assert hits and hits[0]["id"] == f"q{WORDS.index(target)}", seed


# ---------------------------------------------------------------- forecast
@pytest.mark.parametrize("seed", range(200))
def test_a_forecast_is_never_negative_and_has_the_asked_length(seed):
    rng = np.random.default_rng(seed)
    months = int(rng.integers(12, 80))
    index = pd.date_range("2018-01-01", periods=months, freq="MS")
    values = np.clip(rng.normal(100, 60, months), 0, None) * (1 + 0.3 * np.sin(np.arange(months) / 2))
    horizon = int(rng.integers(1, 7))
    result = forecast_demand(pd.Series(values, index=index), horizon=horizon)
    assert result["status"] == "ok" and len(result["forecast"]) == horizon
    assert all(p["quantity"] >= 0 and np.isfinite(p["quantity"]) for p in result["forecast"]), seed
