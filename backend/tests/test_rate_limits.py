"""Failed sign-ins and AI-backed requests are limited per account, per address and per organization."""
import pytest

from app.core.config import settings
from app.core.rate_limit import WINDOW

API = "/api/v1"


async def _email(db, org):
    from bson import ObjectId

    return (await db["users"].find_one({"_id": ObjectId(org["user_id"])}))["email"]


@pytest.fixture(autouse=True)
def fresh_counts():
    WINDOW.clear()
    yield
    WINDOW.clear()


async def test_failed_sign_ins_lock_that_email_for_a_while(api, make_org, monkeypatch, db):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
    email = await _email(db, await make_org("Org L"))
    for _ in range(3):
        assert (await api.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})).status_code == 401
    locked = await api.post(f"{API}/auth/login", json={"email": email, "password": "Passw0rd!Passw0rd"})
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0
    other = await api.post(f"{API}/auth/login", json={"email": "someone-else@example.com", "password": "x"})
    assert other.status_code == 401  # another account is not affected


async def test_a_successful_sign_in_clears_earlier_failures(api, make_org, monkeypatch, db):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    email = await _email(db, await make_org("Org S"))
    assert (await api.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})).status_code == 401
    assert (await api.post(f"{API}/auth/login", json={"email": email, "password": "Passw0rd!Passw0rd"})).status_code == 200
    assert (await api.post(f"{API}/auth/login", json={"email": email, "password": "wrong-password"})).status_code == 401
    assert (await api.post(f"{API}/auth/login", json={"email": email, "password": "Passw0rd!Passw0rd"})).status_code == 200


async def test_one_user_cannot_flood_the_ai_routes(api, org_a, org_b, monkeypatch):
    monkeypatch.setattr(settings, "AI_USER_REQUESTS_PER_MINUTE", 2)
    hsn = f"{API}/analytics/hsn?description=steel+pipe"
    codes = [(await api.get(hsn, headers=org_a["headers"])).status_code for _ in range(3)]
    assert codes[:2] != [429, 429] and codes[2] == 429
    assert (await api.get(hsn, headers=org_b["headers"])).status_code != 429  # other users are unaffected


async def test_an_organization_has_an_hourly_ai_budget(api, make_org, monkeypatch):
    monkeypatch.setattr(settings, "AI_ORG_REQUESTS_PER_HOUR", 1)
    org = await make_org("Org H")
    hsn = f"{API}/analytics/hsn?description=steel+pipe"
    assert (await api.get(hsn, headers=org["headers"])).status_code != 429
    assert (await api.get(hsn, headers=org["headers"])).status_code == 429
