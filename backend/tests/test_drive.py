"""Uploading a purchase order PDF to Google Drive (the last API named in the synopsis).

Drive reuses the Google connection made on the Integrations page, so it needs the same
OAuth client plus the `drive.file` scope, which only touches files this app creates.
"""
import pytest

from tests.test_channels_api import _connect, mailbox, wired  # noqa: F401  (fixture reuse)


@pytest.fixture
async def awarded(api, sourcing):
    """An approved purchase order, ready to file."""
    h = sourcing["headers"]
    po = (await api.post(f"/api/v1/comparisons/procurement-requests/{sourcing['request']['id']}/award",
                         headers=h, json={"quotation_id": sourcing["q_shree"]["id"]})).json()
    await api.post(f"/api/v1/purchase-orders/{po['id']}/approve", headers=h)
    return po


async def test_without_a_google_client_it_says_so_instead_of_failing(api, awarded, sourcing):
    response = await api.post(f"/api/v1/purchase-orders/{awarded['id']}/drive", headers=sourcing["headers"])
    assert response.status_code == 503
    assert "GOOGLE_CLIENT_ID" in response.json()["error"]["message"]


async def test_without_a_connection_it_asks_you_to_connect(api, awarded, sourcing, wired):
    response = await api.post(f"/api/v1/purchase-orders/{awarded['id']}/drive", headers=sourcing["headers"])
    assert response.status_code == 409
    assert "Integrations" in response.json()["error"]["message"]


async def test_uploading_files_the_pdf_and_records_the_link(api, awarded, sourcing, org_a, google, wired):
    await _connect(api, org_a)
    response = await api.post(f"/api/v1/purchase-orders/{awarded['id']}/drive", headers=sourcing["headers"])
    assert response.status_code == 200, response.text
    uploaded = response.json()

    assert uploaded["name"] == f"{awarded['po_number']}.pdf"
    assert uploaded["link"].startswith("https://drive.google.com/")
    assert google.uploads and google.uploads[0]["data"].startswith(b"%PDF")
    assert google.uploads[0]["mime_type"] == "application/pdf"

    stored = (await api.get(f"/api/v1/purchase-orders/{awarded['id']}", headers=sourcing["headers"])).json()
    assert stored["drive_file"]["link"] == uploaded["link"]
    assert [h["action"] for h in stored["history"]][-1] == "filed_to_drive"


async def test_a_revoked_grant_asks_for_a_reconnect_rather_than_500(api, awarded, sourcing, org_a, google, wired):
    await _connect(api, org_a)
    google.valid_refresh_tokens.clear()
    response = await api.post(f"/api/v1/purchase-orders/{awarded['id']}/drive", headers=sourcing["headers"])
    assert response.status_code == 409
    assert "reconnect" in response.json()["error"]["message"].lower()


async def test_another_organization_cannot_file_your_order(api, awarded, org_b, wired):
    assert (await api.post(f"/api/v1/purchase-orders/{awarded['id']}/drive",
                           headers=org_b["headers"])).status_code == 404


def test_drive_scope_is_dropped_when_po_filing_is_off(monkeypatch):
    from app.core.config import settings
    from app.integrations.ingestion.gmail_client import google_scopes

    monkeypatch.setattr(settings, "GOOGLE_DRIVE_ENABLED", False)
    assert "drive.file" not in google_scopes()
