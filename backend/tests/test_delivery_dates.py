"""Quotations that state a delivery *date*, not just a lead time in days.

The synopsis asks for delivery dates to be extracted; until now only "7 days" was captured.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.schemas.extraction import AIExtractionResult
from app.services.procurement.normalizer_service import normalize_quotation


def _extraction(**commercials) -> AIExtractionResult:
    return AIExtractionResult.model_validate({
        "supplier": {"name": "Shree Steel"},
        "items": [{"original_name": "MS plate", "quantity": 10, "unit_price": 72.0}],
        "commercials": commercials,
    })


@pytest.mark.parametrize("stated, expected", [
    ("15/09/2026", date(2026, 9, 15)),          # Indian day-first, the common case here
    ("2026-09-15", date(2026, 9, 15)),          # ISO
    ("15 Sep 2026", date(2026, 9, 15)),
    ("15-09-2026", date(2026, 9, 15)),
])
def test_a_stated_delivery_date_is_normalized(stated, expected):
    normalized = normalize_quotation(_extraction(delivery_date=stated))
    assert normalized.delivery.delivery_date == expected


def test_an_unparsable_or_missing_date_is_left_empty_not_guessed():
    assert normalize_quotation(_extraction(delivery_date="as per schedule")).delivery.delivery_date is None
    assert normalize_quotation(_extraction(delivery_days=7)).delivery.delivery_date is None


def test_delivery_days_are_derived_from_the_date_when_only_a_date_is_given():
    """A comparison scores lead time, so a date-only quotation still needs days."""
    in_ten_days = (datetime.now(timezone.utc) + timedelta(days=10)).date()
    normalized = normalize_quotation(_extraction(delivery_date=in_ten_days.isoformat()))
    assert normalized.delivery.delivery_days == 10


def test_a_stated_date_is_kept_when_both_are_given():
    normalized = normalize_quotation(_extraction(delivery_date="15/09/2026", delivery_days=7))
    assert normalized.delivery.delivery_date == date(2026, 9, 15)
    assert normalized.delivery.delivery_days == 7  # as quoted, not recomputed


async def test_issuing_a_po_uses_the_quoted_delivery_date(api, db, sourcing):
    """The PO's expected delivery date should follow the supplier's own commitment."""
    from app.repositories.quotations import QuotationRepository

    h, org_id = sourcing["headers"], sourcing["q_shree"]["organization_id"]
    promised = (datetime.now(timezone.utc) + timedelta(days=21)).date()
    await QuotationRepository(db).store_stage(
        org_id, sourcing["q_shree"]["id"], "effective_data.delivery.delivery_date", promised.isoformat())

    po = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/award",
                         headers=h, json={"quotation_id": sourcing["q_shree"]["id"]})).json()
    assert po["terms"]["delivery_date"] == promised.isoformat()

    await api.post(f"/api/v1/purchase-orders/{po['id']}/approve", headers=h)
    issued = (await api.post(f"/api/v1/purchase-orders/{po['id']}/issue", headers=h)).json()
    assert issued["expected_delivery_date"][:10] == promised.isoformat()
