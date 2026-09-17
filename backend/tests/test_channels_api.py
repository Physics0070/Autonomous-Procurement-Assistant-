"""Connect, sync and disconnect Gmail through the HTTP API."""
import httpx
import pytest

from app.api.deps import storage as storage_dependency
from app.api.routes.channels import get_enqueue, get_gmail_client
from app.core.config import settings
from app.core.security import create_oauth_state
from app.integrations.ingestion.gmail_client import GmailClient
from tests.fakes.google import FakeAttachment, FakeGoogle, FakeMessage

API = "/api/v1/channels"


@pytest.fixture
def mailbox(google):
    google.add_message(FakeMessage(
        id="m1",
        sender="Shree Plastics <sales@shreeplastics.co.in>",
        subject="Quotation SP/2026/0417",
        body="Attached.",
        attachments=[FakeAttachment("SP-0417.pdf", "application/pdf", b"%PDF-1.4 q")],
    ))
    return google


@pytest.fixture
def wired(api, mailbox, storage):
    from app.main import app

    enqueued: list[tuple[str, str]] = []

    async def fake_client():
        async with httpx.AsyncClient(transport=mailbox.transport) as http:
            yield GmailClient(http)

    async def fake_enqueue(organization_id: str, quotation_id: str) -> None:
        enqueued.append((organization_id, quotation_id))

    app.dependency_overrides[get_gmail_client] = fake_client
    app.dependency_overrides[get_enqueue] = lambda: fake_enqueue
    app.dependency_overrides[storage_dependency] = lambda: storage
    return enqueued


async def _connect(api, org, code="good-code"):
    state = create_oauth_state(
        organization_id=org["org_id"], user_id=org["user_id"], provider="gmail"
    )
    return await api.get(f"{API}/gmail/callback", params={"code": code, "state": state})


async def test_authorize_requires_google_credentials(api, org_a, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    response = await api.get(f"{API}/gmail/authorize", headers=org_a["headers"])
    assert response.status_code == 503
    assert "GOOGLE_CLIENT_ID" in response.json()["error"]["message"]


async def test_authorize_returns_a_consent_url(api, org_a, google):
    response = await api.get(f"{API}/gmail/authorize", headers=org_a["headers"])
    assert response.status_code == 200
    url = httpx.URL(response.json()["authorize_url"])
    assert url.host == "accounts.google.com"
    assert url.params["client_id"] == "client-123.apps.googleusercontent.com"


async def test_members_cannot_connect_a_mailbox(api, make_org, google):
    member = await make_org("Members Only", role="member")
    response = await api.get(f"{API}/gmail/authorize", headers=member["headers"])
    assert response.status_code == 403


async def test_a_forged_state_is_rejected(api, wired):
    response = await api.get(f"{API}/gmail/callback", params={"code": "good-code", "state": "forged"})
    assert response.status_code == 303
    assert response.headers["location"].startswith("http://localhost:5173/integrations?gmail=error")


async def test_a_denied_consent_is_reported(api, org_a, wired):
    state = create_oauth_state(organization_id=org_a["org_id"], user_id=org_a["user_id"], provider="gmail")
    response = await api.get(f"{API}/gmail/callback", params={"error": "access_denied", "state": state})
    assert "gmail=error" in response.headers["location"]


async def test_missing_offline_access_is_reported(api, org_a, mailbox, wired):
    mailbox.omit_refresh_token = True
    response = await _connect(api, org_a)
    assert "gmail=error" in response.headers["location"]
    listed = await api.get(API, headers=org_a["headers"])
    assert listed.json()["gmail"]["connected"] is False


async def test_connecting_stores_an_encrypted_token_that_is_never_returned(api, db, org_a, wired):
    response = await _connect(api, org_a)
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/integrations?gmail=connected"

    raw = await db.channel_connections.find_one({"provider": "gmail"})
    assert raw["account_email"] == FakeGoogle.ACCOUNT
    assert "refresh-1" not in raw["encrypted_refresh_token"]

    body = (await api.get(API, headers=org_a["headers"])).json()
    assert body["gmail"]["connected"] is True
    assert body["gmail"]["account_email"] == FakeGoogle.ACCOUNT
    assert body["gmail"]["configured"] is True
    assert body["whatsapp"]["status"] == "planned"
    assert "encrypted_refresh_token" not in str(body)
    assert "refresh-1" not in str(body)


async def test_sync_imports_and_records_the_outcome(api, org_a, wired):
    await _connect(api, org_a)
    response = await api.post(f"{API}/gmail/sync", headers=org_a["headers"])
    assert response.status_code == 200
    assert response.json()["documents_imported"] == 1
    assert len(wired) == 1

    quotations = (await api.get("/api/v1/quotations", headers=org_a["headers"])).json()
    assert quotations["items"][0]["source"]["type"] == "email"

    gmail = (await api.get(API, headers=org_a["headers"])).json()["gmail"]
    assert gmail["last_result"]["documents_imported"] == 1
    assert gmail["last_synced_at"] is not None
    assert gmail["last_error"] is None


async def test_revoked_access_asks_for_a_reconnect_without_logging_out(api, org_a, mailbox, wired):
    await _connect(api, org_a)
    mailbox.valid_refresh_tokens.clear()
    response = await api.post(f"{API}/gmail/sync", headers=org_a["headers"])
    assert response.status_code == 409
    assert "Reconnect Gmail" in response.json()["error"]["message"]

    gmail = (await api.get(API, headers=org_a["headers"])).json()["gmail"]
    assert gmail["status"] == "reauthorization_required"
    assert gmail["connected"] is False

    again = await api.post(f"{API}/gmail/sync", headers=org_a["headers"])
    assert again.status_code == 409


async def test_reconnecting_clears_the_reconnect_state(api, org_a, mailbox, wired):
    await _connect(api, org_a)
    mailbox.valid_refresh_tokens.clear()
    await api.post(f"{API}/gmail/sync", headers=org_a["headers"])
    mailbox.valid_refresh_tokens.add("refresh-1")
    await _connect(api, org_a)
    gmail = (await api.get(API, headers=org_a["headers"])).json()["gmail"]
    assert gmail["status"] == "connected"
    assert gmail["last_error"] is None


async def test_disconnect_revokes_and_removes(api, org_a, mailbox, wired):
    await _connect(api, org_a)
    response = await api.delete(f"{API}/gmail", headers=org_a["headers"])
    assert response.status_code == 204
    assert mailbox.revoked == ["refresh-1"]
    assert (await api.get(API, headers=org_a["headers"])).json()["gmail"]["connected"] is False
    assert (await api.delete(f"{API}/gmail", headers=org_a["headers"])).status_code == 404


async def test_connections_are_isolated_between_organizations(api, org_a, org_b, wired):
    await _connect(api, org_a)
    other = (await api.get(API, headers=org_b["headers"])).json()["gmail"]
    assert other["connected"] is False
    assert other.get("account_email") is None
    assert (await api.post(f"{API}/gmail/sync", headers=org_b["headers"])).status_code == 422
    assert (await api.delete(f"{API}/gmail", headers=org_b["headers"])).status_code == 404
