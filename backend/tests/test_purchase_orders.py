"""Award -> PO draft, GST split, lifecycle, delivery recording, PDF."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.automation.purchase_orders import record_delivery, tax_split


async def award(api, s, quotation="q_shree"):
    return await api.post(f"/api/v1/comparisons/procurement-requests/{s['request']['id']}/award",
                          headers=s["headers"], json={"quotation_id": s[quotation]["id"]})


def test_tax_split():
    same = tax_split({18: 1000}, "27AABCV1234K1Z5", "27AABCS1429B1ZQ")
    assert same == [{"name": "CGST", "rate": 9, "amount": 90}, {"name": "SGST", "rate": 9, "amount": 90}]
    assert tax_split({18: 1000}, "27AABCV1234K1Z5", "29ABCDE1234F2Z5") == [{"name": "IGST", "rate": 18, "amount": 180}]
    assert tax_split({18: 1000}, None, "29ABCDE1234F2Z5") == [{"name": "GST", "rate": 18, "amount": 180}]


def test_delivery_recording():
    expected = datetime(2026, 9, 10, tzinfo=timezone.utc)
    assert record_delivery(expected, expected + timedelta(hours=5))["on_time"] is True
    late = record_delivery(expected, expected + timedelta(days=3))
    assert (late["on_time"], late["delay_days"]) == (False, 3)
    assert record_delivery(None, expected)["on_time"] is None


async def test_award_builds_the_po_from_matched_items(api, sourcing):
    response = await award(api, sourcing)
    assert response.status_code == 201, response.text
    po = response.json()
    assert po["po_number"] == f"PO-{datetime.now().year}-0001" and po["status"] == "draft"
    assert [(l["description"], l["quantity"], l["unit_price"], l["line_total"]) for l in po["lines"]] == [
        ("MS plate 10mm", 100, 72.0, 7200.0), ("Hex bolt M12", 500, 8.5, 4250.0)]
    # Both GSTINs are in Maharashtra -> CGST + SGST.
    assert [t["name"] for t in po["pricing"]["taxes"]] == ["CGST", "SGST"]
    assert po["pricing"]["total"] == pytest.approx(11450 * 1.18 + 1500)
    assert po["warnings"] == []
    request = (await api.get(f"/api/v1/procurement-requests/{sourcing['request']['id']}", headers=sourcing["headers"])).json()
    assert request["status"] == "awarded"


async def test_unmatched_items_are_warned_and_numbers_are_sequential(api, sourcing):
    await award(api, sourcing)
    po = (await award(api, sourcing, "q_apex")).json()
    assert po["po_number"].endswith("-0002")
    assert [l["description"] for l in po["lines"]] == ["MS plate 10mm"]
    assert "Hex bolt M12" in po["warnings"][0]
    assert [t["name"] for t in po["pricing"]["taxes"]] == ["IGST"]


async def test_lifecycle_delivery_and_pdf(api, sourcing):
    h, po = sourcing["headers"], (await award(api, sourcing)).json()
    base = f"/api/v1/purchase-orders/{po['id']}"
    assert (await api.post(f"{base}/issue", headers=h)).status_code == 409
    await api.post(f"{base}/approve", headers=h)
    drafts = (await api.get("/api/v1/communications?kind=purchase_order", headers=h)).json()
    assert len(drafts) == 1 and drafts[0]["purchase_order_id"] == po["id"] and drafts[0]["status"] == "draft"

    issued = (await api.post(f"{base}/issue", headers=h)).json()
    assert issued["expected_delivery_date"]
    late = (datetime.now(timezone.utc) + timedelta(days=9)).isoformat()
    delivered = (await api.post(f"{base}/deliver", headers=h, json={"delivered_at": late})).json()
    assert (delivered["status"], delivered["on_time"], delivered["delay_days"]) == ("delivered", False, 2)
    assert (await api.post(f"{base}/cancel", headers=h)).status_code == 409
    assert (await api.post(f"{base}/close", headers=h)).json()["status"] == "closed"

    pdf = await api.get(f"{base}/pdf", headers=h)
    assert pdf.content.startswith(b"%PDF") and po["po_number"] in pdf.headers["content-disposition"]


async def test_members_cannot_award_and_orders_are_isolated(api, sourcing, make_org, org_b):
    po = (await award(api, sourcing)).json()
    assert (await api.get(f"/api/v1/purchase-orders/{po['id']}", headers=org_b["headers"])).status_code == 404
    assert (await api.get("/api/v1/purchase-orders", headers=org_b["headers"])).json() == []
    member = await make_org("Member Org", role="member")
    response = await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/award",
                              headers=member["headers"], json={"quotation_id": sourcing["q_shree"]["id"]})
    assert response.status_code == 403
