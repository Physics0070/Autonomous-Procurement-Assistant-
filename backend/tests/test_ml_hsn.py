"""HSN code suggestion from a quotation line, against the official GST HSN master."""
import pandas as pd
import pytest

from ml.hsn import BENCHMARK_PATH, HsnIndex, normalize_item

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def index():
    return HsnIndex.load()


def test_the_official_master_is_loaded(index):
    assert index.heading_count > 1000   # 4-digit headings in the GST portal file
    assert index.describe("7318").startswith("SCREWS, BOLTS, NUTS")


def test_text_matching_puts_the_right_heading_on_the_shortlist(index):
    """Text matching only has to shortlist; picking top-1 is the model's job (it ranks
    "fabric coated with PVC" above "PVC pipe", which is exactly why the model step exists)."""
    shortlist = index.suggest("PVC pipe 2 inch", k=30)
    assert "3917" in [s["heading"] for s in shortlist]
    assert len(shortlist) == 30 and all(s["description"] for s in shortlist)


def test_indian_trade_abbreviations_are_expanded():
    assert "non-alloy steel" in normalize_item("MS Plate 10mm")
    assert "stainless steel" in normalize_item("SS 304 sheet")
    assert "galvanised" in normalize_item("GI sheet")


def test_every_benchmark_label_is_a_real_heading(index):
    bench = pd.read_csv(BENCHMARK_PATH, dtype=str)
    assert set(bench["split"]) == {"dev", "test"}
    assert all(index.describe(h) for h in bench["heading"])


async def test_the_model_picks_from_the_official_shortlist(index):
    from ml.hsn import classify_hsn
    from tests.fakes.llm import ScriptedProvider

    model = ScriptedProvider(responses=['{"heading": "3917", "confidence": 0.93, "reason": "plastic pipe"}'])
    result = await classify_hsn("PVC pipe 2 inch", model, index=index)
    assert (result["heading"], result["method"]) == ("3917", "llm")
    assert "3917" in model.calls[0]["prompt"]           # the official candidates were shown to it
    assert result["description"].startswith("TUBES, PIPES AND HOSES")


async def test_the_model_may_name_a_real_heading_outside_the_shortlist(index):
    from ml.hsn import classify_hsn
    from tests.fakes.llm import ScriptedProvider

    model = ScriptedProvider(responses=['{"heading": "8471", "confidence": 0.9, "reason": "a laptop"}'])
    result = await classify_hsn("Laptop i5 16GB", model, index=index)
    assert result["heading"] == "8471" and result["method"] == "llm"


async def test_an_invented_heading_is_rejected_and_text_matching_is_used(index):
    from ml.hsn import classify_hsn
    from tests.fakes.llm import ScriptedProvider

    model = ScriptedProvider(responses=['{"heading": "9999", "confidence": 0.99}'])
    result = await classify_hsn("PVC pipe 2 inch", model, index=index)
    assert result["method"] == "text_match" and "9999" in result["note"]
    assert result["heading"] == index.suggest("PVC pipe 2 inch", k=1)[0]["heading"]


async def test_without_a_model_it_falls_back_to_text_matching(index):
    from app.integrations.ai.base import UnconfiguredProvider
    from ml.hsn import classify_hsn

    result = await classify_hsn("PVC pipe 2 inch", UnconfiguredProvider("no key"), index=index)
    assert result["method"] == "text_match" and "no key" in result["note"]


async def test_the_api_suggests_an_hsn_heading(api, org_a):
    response = await api.get("/api/v1/analytics/hsn", params={"item": "PVC pipe 2 inch"}, headers=org_a["headers"])
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["method"] == "text_match" and len(body["heading"]) == 4  # no key in tests
