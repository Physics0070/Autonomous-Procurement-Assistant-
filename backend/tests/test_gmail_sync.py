"""Gmail messages -> the shared ingestion pipeline."""
import httpx
import pytest

from app.core.crypto import encrypt_secret
from app.integrations.ingestion.gmail_client import GmailAuthError, GmailClient
from app.repositories.quotations import QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.services.channels.gmail_sync import sync_gmail
from tests.fakes.google import FakeAttachment, FakeGoogle, FakeMessage

PDF = b"%PDF-1.4\n% supplier quotation\n"
XLSX = b"PK\x03\x04 fake workbook"
PNG = b"\x89PNG\r\n\x1a\n fake logo"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
def mailbox(google):
    google.add_message(FakeMessage(
        id="m1",
        sender='"Shree Plastics" <sales@shreeplastics.co.in>',
        subject="Quotation SP/2026/0417",
        body="Quotation attached.",
        attachments=[
            FakeAttachment("SP-0417.pdf", "application/pdf", PDF),
            FakeAttachment("rates.xlsx", XLSX_MIME, XLSX),
            FakeAttachment("archive.zip", "application/zip", b"PK\x03\x04zip"),
            FakeAttachment("logo.png", "image/png", PNG, inline=True),
        ],
    ))
    google.add_message(FakeMessage(
        id="m2",
        sender="Balaji Hardware <balaji.hw@balaji-demo.com>",
        subject="Rate quote for PVC pipe",
        body="PVC PIPE 2 INCH  100 Nos  292  29200\nDelivery 5 days",
    ))
    google.add_message(FakeMessage(
        id="m3",
        sender="Newsletter <news@example-news.com>",
        subject="Weekly digest",
        body="Nothing to buy here.",
    ))
    return google


async def _run(db, org_id, google, storage, enqueued):
    async def enqueue(organization_id: str, quotation_id: str) -> None:
        enqueued.append((organization_id, quotation_id))

    async with httpx.AsyncClient(transport=google.transport) as http:
        return await sync_gmail(
            organization_id=org_id,
            connection={
                "encrypted_refresh_token": encrypt_secret("refresh-1"),
                "account_email": FakeGoogle.ACCOUNT,
            },
            client=GmailClient(http),
            quotations=QuotationRepository(db),
            suppliers=SupplierRepository(db),
            storage=storage,
            enqueue=enqueue,
            query="subject:quotation",
            max_messages=25,
        )


async def test_imports_attachments_and_quotation_bodies(db, org_a, storage, mailbox):
    enqueued = []
    result = await _run(db, org_a["org_id"], mailbox, storage, enqueued)

    assert result.messages_scanned == 3
    assert result.documents_imported == 3          # pdf + xlsx + m2 body
    assert result.attachments_ignored == 1         # zip; the inline logo is not an attachment
    assert result.errors == []
    assert [quotation for _, quotation in enqueued] == result.quotation_ids

    rows = await QuotationRepository(db).list_filtered(org_a["org_id"])
    by_name = {row["source"]["original_filename"]: row for row in rows}
    assert set(by_name) == {"SP-0417.pdf", "rates.xlsx", "email-m2.txt"}

    pdf = by_name["SP-0417.pdf"]
    assert pdf["source"]["type"] == "email"
    assert pdf["source"]["external_reference"] == "gmail:m1:1"
    assert pdf["source"]["metadata"]["sender_email"] == "sales@shreeplastics.co.in"
    assert pdf["source"]["metadata"]["subject"] == "Quotation SP/2026/0417"
    assert pdf["document_type"] == "pdf_digital"

    body = await storage.load(by_name["email-m2.txt"]["source"]["storage_key"])
    assert b"PVC PIPE 2 INCH" in body
    assert b"Subject: Rate quote for PVC pipe" in body


async def test_a_second_sync_imports_nothing_new(db, org_a, storage, mailbox):
    await _run(db, org_a["org_id"], mailbox, storage, [])
    enqueued = []
    result = await _run(db, org_a["org_id"], mailbox, storage, enqueued)
    assert result.documents_imported == 0
    assert result.duplicates_skipped == 3
    assert enqueued == []
    assert await QuotationRepository(db).count(org_a["org_id"]) == 3


async def test_a_known_sender_is_linked_to_the_supplier(db, org_a, storage, mailbox):
    supplier = await SupplierRepository(db).create(
        org_a["org_id"], {"name": "Shree Plastics", "email": "sales@shreeplastics.co.in"}
    )
    await _run(db, org_a["org_id"], mailbox, storage, [])
    rows = await QuotationRepository(db).list_filtered(org_a["org_id"], supplier_id=supplier["id"])
    assert {row["source"]["original_filename"] for row in rows} == {"SP-0417.pdf", "rates.xlsx"}


async def test_mail_sent_from_the_connected_mailbox_is_skipped(db, org_a, storage, mailbox):
    mailbox.add_message(FakeMessage(
        id="m4",
        sender=f"Purchase Team <{FakeGoogle.ACCOUNT}>",
        subject="RFQ: PVC pipe quotation request",
        body="Please send your quotation.",
    ))
    result = await _run(db, org_a["org_id"], mailbox, storage, [])
    names = {
        row["source"]["original_filename"]
        for row in await QuotationRepository(db).list_filtered(org_a["org_id"])
    }
    assert result.messages_scanned == 4
    assert "email-m4.txt" not in names


async def test_one_broken_message_does_not_stop_the_sync(db, org_a, storage, mailbox):
    mailbox.add_message(FakeMessage(
        id="m0",
        sender="Empty Supplier <empty@empty-demo.com>",
        subject="Quotation attached",
        attachments=[FakeAttachment("blank.pdf", "application/pdf", b"")],
    ))
    result = await _run(db, org_a["org_id"], mailbox, storage, [])
    assert result.documents_imported == 3
    assert len(result.errors) == 1
    assert result.errors[0].startswith("m0:")


async def test_a_revoked_grant_stops_the_sync(db, org_a, storage, mailbox):
    mailbox.valid_refresh_tokens.clear()
    with pytest.raises(GmailAuthError):
        await _run(db, org_a["org_id"], mailbox, storage, [])
