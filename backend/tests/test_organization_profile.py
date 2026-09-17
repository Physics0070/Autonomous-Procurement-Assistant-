"""Organization profile (the buyer block on purchase orders) and GSTIN rules."""
import pytest

from app.core.gstin import is_valid_gstin, normalize_gstin, state_code, state_name
from app.services.documents.ai_extraction import heuristic_extraction
from app.services.procurement.validation import validate_extraction
from app.schemas.document import ProcessedDocument
from app.schemas.extraction import AIExtractionResult


@pytest.mark.parametrize("value", ["27AABCS1429B1ZQ", "27AAGCM4455K1Z8", "29ABCDE1234F2Z5", " 27aabcs1429b1zq "])
def test_valid_gstins(value):
    assert is_valid_gstin(value)


@pytest.mark.parametrize("value", ["", None, "27AABCS1429B1Q", "AB1234567890123", "27AABCS1429B1XQ", "27AABCS1429B0ZQ"])
def test_invalid_gstins(value):
    assert not is_valid_gstin(value)


def test_state_is_read_from_the_gstin():
    assert normalize_gstin(" 27aagcm4455k1z8 ") == "27AAGCM4455K1Z8"
    assert state_code("27AAGCM4455K1Z8") == "27"
    assert state_name("27AAGCM4455K1Z8") == "Maharashtra"
    assert state_name("29ABCDE1234F2Z5") == "Karnataka"
    assert state_code("not a gstin") is None


def test_heuristic_extraction_finds_a_gstin_ending_in_a_digit():
    document = ProcessedDocument(raw_text="MARUTI TRADERS\nGST No: 27AAGCM4455K1Z8\nGrand Total 100")
    assert heuristic_extraction(document).supplier.gst_number == "27AAGCM4455K1Z8"


def test_validation_accepts_a_gstin_ending_in_a_digit():
    extraction = AIExtractionResult.model_validate({"supplier": {"name": "Maruti", "gst_number": "27AAGCM4455K1Z8"}})
    codes = {issue.code for issue in validate_extraction(extraction).issues}
    assert "invalid_gst_format" not in codes


async def test_profile_starts_empty(api, org_a):
    response = await api.get("/api/v1/organizations/me", headers=org_a["headers"])
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Org A"
    assert body["gst_number"] is None


async def test_admin_updates_the_profile(api, org_a):
    response = await api.put(
        "/api/v1/organizations/me",
        headers=org_a["headers"],
        json={
            "name": "Vishwakarma Engineering Works",
            "address": "Plot 7, Bibwewadi, Pune 411037",
            "gst_number": "27aabcv1234k1z5",
            "contact_email": "purchase@vishwakarma-eng.com",
            "contact_phone": "+91 20 2421 0000",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Vishwakarma Engineering Works"
    assert body["gst_number"] == "27AABCV1234K1Z5"
    assert body["state_code"] == "27"
    assert body["state"] == "Maharashtra"

    me = await api.get("/api/v1/auth/me", headers=org_a["headers"])
    assert me.json()["organization"]["name"] == "Vishwakarma Engineering Works"


async def test_an_invalid_gstin_is_rejected(api, org_a):
    response = await api.put("/api/v1/organizations/me", headers=org_a["headers"],
                             json={"gst_number": "NOT-A-GSTIN"})
    assert response.status_code == 422


async def test_members_cannot_change_the_profile(api, make_org):
    member = await make_org("Member Org", role="member")
    response = await api.put("/api/v1/organizations/me", headers=member["headers"],
                             json={"address": "Somewhere"})
    assert response.status_code == 403


async def test_profile_changes_stay_inside_the_organization(api, org_a, org_b):
    await api.put("/api/v1/organizations/me", headers=org_a["headers"], json={"address": "Pune"})
    other = await api.get("/api/v1/organizations/me", headers=org_b["headers"])
    assert other.json()["address"] is None
