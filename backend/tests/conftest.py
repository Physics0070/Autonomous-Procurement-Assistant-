"""Shared fixtures.

Database tests run against the local MongoDB in a throwaway database that is
dropped after every test. External services (Google, OpenRouter) are replaced
by in-memory fakes, so no credentials are needed.
"""
from __future__ import annotations

import os
import uuid

# Must be set before anything imports `app.core.config`.
os.environ["MONGODB_DB_NAME"] = "procurement_assistant_test"
os.environ["GMAIL_SYNC_INTERVAL_MINUTES"] = "0"
os.environ["AI_PROVIDER"] = "none"

import httpx  # noqa: E402
import pytest  # noqa: E402

TEST_DB = "procurement_assistant_test"


@pytest.fixture
async def db():
    from app.core import database

    connection = await database.connect_to_database(db_name=TEST_DB)
    yield connection
    await connection.client.drop_database(TEST_DB)
    await database.close_database_connection()


@pytest.fixture
def make_org(db):
    from app.core.security import create_access_token, hash_password
    from app.repositories.users import OrganizationRepository, UserRepository

    async def _make(name: str, role: str = "admin") -> dict:
        organization = await OrganizationRepository(db).create(name, "Manufacturing")
        user = await UserRepository(db).create(
            name=f"{name} User",
            email=f"user-{uuid.uuid4().hex[:10]}@org-{uuid.uuid4().hex[:6]}.com",
            hashed_password=hash_password("Passw0rd!Passw0rd"),
            organization_id=organization["id"],
            role=role,
        )
        token = create_access_token(
            str(user["id"]), {"org": organization["id"], "role": role}
        )
        return {
            "org_id": organization["id"],
            "user_id": str(user["id"]),
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return _make


@pytest.fixture
async def org_a(make_org):
    return await make_org("Org A")


@pytest.fixture
async def org_b(make_org):
    return await make_org("Org B")


@pytest.fixture
def storage(tmp_path):
    from app.services.storage.local import LocalStorageBackend

    return LocalStorageBackend(root=str(tmp_path / "storage"))


@pytest.fixture
async def api(db):
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def google(monkeypatch):
    """Google credentials configured, plus an empty fake Google backend."""
    from app.core.config import settings
    from tests.fakes.google import FakeGoogle

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "client-123.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "secret-xyz")
    monkeypatch.setattr(settings, "FRONTEND_URL", "http://localhost:5173")
    return FakeGoogle()


@pytest.fixture
async def sourcing(api, db, org_a):
    """A request for two items, two processed quotations and a stored comparison.

    Shree Steel (Maharashtra GSTIN) quotes both items; Apex Metals (Karnataka)
    quotes only the first and is cheaper per unit but slower.
    """
    from bson import ObjectId

    from app.repositories.quotations import QuotationRepository

    h = org_a["headers"]
    await api.put("/api/v1/organizations/me", headers=h, json={"gst_number": "27AABCV1234K1Z5", "address": "Pune"})
    shree = (await api.post("/api/v1/suppliers", headers=h, json={
        "name": "Shree Steel", "email": "sales@shreesteel.com", "gst_number": "27AABCS1429B1ZQ"})).json()
    apex = (await api.post("/api/v1/suppliers", headers=h, json={
        "name": "Apex Metals", "email": "quotes@apexmetals.com", "gst_number": "29ABCDE1234F2Z5"})).json()
    request = (await api.post("/api/v1/procurement-requests", headers=h, json={
        "title": "MS plates for press line",
        "items": [{"name": "MS plate 10mm", "quantity": 100, "unit": "kg", "specifications": "IS 2062"},
                  {"name": "Hex bolt M12", "quantity": 500, "unit": "pcs"}]})).json()
    item1, item2 = (i["item_id"] for i in request["items"])

    def quotation(supplier, lines, delivery_days, payment_days, freight):
        subtotal = sum(q * p for _, _, q, p in lines)
        return {
            "procurement_request_id": ObjectId(request["id"]), "supplier_id": ObjectId(supplier["id"]),
            "supplier_name": supplier["name"], "processing_status": "COMPLETED",
            "effective_data": {
                "supplier": {"name": supplier["name"], "gst_number": supplier["gst_number"]},
                "items": [{"line_id": lid, "original_name": lid, "quantity": q, "unit_price": p, "tax_percentage": 18}
                          for lid, _, q, p in lines],
                "pricing": {"currency": "INR", "subtotal": subtotal, "tax_percentage": 18,
                            "transportation_cost": freight, "landed_total": round(subtotal * 1.18 + freight, 2)},
                "delivery": {"delivery_days": delivery_days},
                "payment_terms": {"payment_days": payment_days, "raw_terms": f"{payment_days} days credit"},
            },
            "match_result": {
                "matches": [{"request_item_id": rid, "request_item_name": rid, "quotation_line_id": lid,
                             "matched": True, "unit_price": p} for lid, rid, _, p in lines],
                "matched_count": len(lines), "coverage": len(lines) / 2,
            },
        }

    repo = QuotationRepository(db)
    q_shree = await repo.create(org_a["org_id"], quotation(
        shree, [("L1", item1, 100, 72.0), ("L2", item2, 500, 8.5)], 7, 30, 1500))
    q_apex = await repo.create(org_a["org_id"], quotation(apex, [("L1", item1, 100, 68.0)], 30, 0, 800))
    comparison = await api.post(f"/api/v1/comparisons/procurement-requests/{request['id']}", headers=h,
                                json={"include_ai_explanation": False})
    assert comparison.status_code == 200, comparison.text
    return {"headers": h, "request": request, "shree": shree, "apex": apex,
            "q_shree": q_shree, "q_apex": q_apex, "comparison": comparison.json()}
