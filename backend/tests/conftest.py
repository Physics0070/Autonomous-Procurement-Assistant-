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
