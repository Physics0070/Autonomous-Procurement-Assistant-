"""Gmail REST + OAuth client, exercised against the fake Google backend."""
import httpx
import pytest

from app.integrations.ingestion.gmail_client import (
    GmailAuthError,
    GmailClient,
    build_authorize_url,
    decode_base64url,
    extract_plain_body,
    iter_parts,
    parse_sender_email,
)
from tests.fakes.google import FakeAttachment, FakeGoogle, FakeMessage, b64url


@pytest.fixture
def mailbox(google):
    google.add_message(
        FakeMessage(
            id="m1",
            sender='"Shree Plastics" <Sales@ShreePlastics.co.in>',
            subject="Quotation SP/2026/0417",
            body="Please find our quotation attached.",
            attachments=[FakeAttachment("quote.pdf", "application/pdf", b"%PDF-1.4 test")],
        )
    )
    return google


def test_consent_url_requests_offline_read_only_access(google):
    url = httpx.URL(build_authorize_url("state-abc"))
    assert url.host == "accounts.google.com"
    assert url.params["client_id"] == "client-123.apps.googleusercontent.com"
    assert url.params["access_type"] == "offline"
    assert url.params["prompt"] == "consent"
    assert url.params["state"] == "state-abc"
    assert url.params["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert url.params["redirect_uri"].endswith("/api/v1/channels/gmail/callback")


def test_base64url_without_padding_decodes():
    assert decode_base64url(b64url(b"quotation")) == b"quotation"


def test_sender_email_is_extracted_and_lowercased():
    assert parse_sender_email('"Shree Plastics" <Sales@ShreePlastics.co.in>') == "sales@shreeplastics.co.in"
    assert parse_sender_email("not an address") is None
    assert parse_sender_email(None) is None


def test_mime_walk_finds_nested_text_and_attachment(mailbox):
    full = mailbox.messages["m1"].to_full({"1": "att-1"})
    kinds = [part["mimeType"] for part in iter_parts(full["payload"])]
    assert kinds == [
        "multipart/mixed", "multipart/alternative", "text/plain", "text/html", "application/pdf",
    ]
    assert extract_plain_body(full) == "Please find our quotation attached."


async def test_exchange_refresh_profile_list_message_and_attachment(mailbox):
    async with httpx.AsyncClient(transport=mailbox.transport) as http:
        client = GmailClient(http)
        grant = await client.exchange_code("good-code")
        assert grant.refresh_token == "refresh-1"
        assert grant.scope == FakeGoogle.SCOPE
        access = await client.refresh_access_token(grant.refresh_token)
        assert await client.get_profile_email(access) == FakeGoogle.ACCOUNT
        assert await client.list_message_ids(access, "subject:quotation", 10) == ["m1"]
        message = await client.get_message(access, "m1")
        attachment = list(iter_parts(message["payload"]))[-1]
        data = await client.get_attachment(access, "m1", attachment["body"]["attachmentId"])
        assert data == b"%PDF-1.4 test"


async def test_empty_mailbox_lists_nothing(google):
    async with httpx.AsyncClient(transport=google.transport) as http:
        client = GmailClient(http)
        access = await client.refresh_access_token("refresh-1")
        assert await client.list_message_ids(access, "subject:quotation", 10) == []


async def test_revoked_refresh_token_is_an_auth_error(google):
    async with httpx.AsyncClient(transport=google.transport) as http:
        with pytest.raises(GmailAuthError):
            await GmailClient(http).refresh_access_token("revoked-token")


async def test_rejected_access_token_is_an_auth_error(google):
    async with httpx.AsyncClient(transport=google.transport) as http:
        with pytest.raises(GmailAuthError):
            await GmailClient(http).get_profile_email("ya29.never-issued")


async def test_revoke_posts_the_token(google):
    async with httpx.AsyncClient(transport=google.transport) as http:
        await GmailClient(http).revoke("refresh-1")
    assert google.revoked == ["refresh-1"]
