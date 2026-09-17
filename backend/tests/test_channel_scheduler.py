"""Automatic Gmail collection across organizations."""
import httpx
import pytest

from app.core.config import settings
from app.core.crypto import encrypt_secret
from app.integrations.ingestion.gmail_client import GmailClient
from app.repositories.channels import ChannelConnectionRepository
from app.workers.channel_scheduler import ChannelScheduler, sync_all_gmail
from tests.fakes.google import FakeAttachment, FakeGoogle, FakeMessage


@pytest.fixture
def mailbox(google):
    google.add_message(FakeMessage(
        id="m1",
        sender="Shree Plastics <sales@shreeplastics.co.in>",
        subject="Quotation",
        attachments=[FakeAttachment("q.pdf", "application/pdf", b"%PDF-1.4 q")],
    ))
    return google


async def _connect(channels, org_id, refresh_token):
    await channels.upsert_for_provider(org_id, "gmail", {
        "status": "connected",
        "account_email": FakeGoogle.ACCOUNT,
        "encrypted_refresh_token": encrypt_secret(refresh_token),
    })


async def test_every_connected_organization_is_synced(db, make_org, storage, mailbox):
    channels = ChannelConnectionRepository(db)
    healthy = [await make_org("North"), await make_org("South")]
    revoked = await make_org("Revoked")
    for org in healthy:
        await _connect(channels, org["org_id"], "refresh-1")
    await _connect(channels, revoked["org_id"], "refresh-that-google-revoked")

    enqueued = []

    async def enqueue(organization_id, quotation_id):
        enqueued.append((organization_id, quotation_id))

    async with httpx.AsyncClient(transport=mailbox.transport) as http:
        summary = await sync_all_gmail(
            database=db, client=GmailClient(http), storage=storage, enqueue=enqueue
        )

    assert summary == {"organizations": 3, "imported": 2, "failed": 1}
    assert {org for org, _ in enqueued} == {healthy[0]["org_id"], healthy[1]["org_id"]}
    broken = await channels.get_for_provider(revoked["org_id"], "gmail")
    assert broken["status"] == "reauthorization_required"
    assert len(await channels.list_active("gmail")) == 2


async def test_nothing_connected_is_a_quiet_no_op(db, storage, google):
    async with httpx.AsyncClient(transport=google.transport) as http:
        summary = await sync_all_gmail(
            database=db, client=GmailClient(http), storage=storage, enqueue=None
        )
    assert summary == {"organizations": 0, "imported": 0, "failed": 0}


def test_disabled_without_google_credentials(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    assert ChannelScheduler(interval_minutes=15).enabled is False


def test_enabled_only_with_credentials_and_an_interval(google):
    assert ChannelScheduler(interval_minutes=0).enabled is False
    assert ChannelScheduler(interval_minutes=15).enabled is True


async def test_start_and_stop_are_safe_when_disabled(google):
    scheduler = ChannelScheduler(interval_minutes=0)
    await scheduler.start()
    await scheduler.stop()


async def test_start_and_stop_cancel_the_background_task(google):
    scheduler = ChannelScheduler(interval_minutes=15)
    await scheduler.start()
    assert scheduler._task is not None
    await scheduler.stop()
    assert scheduler._task is None
