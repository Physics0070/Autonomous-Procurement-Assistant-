"""Automatic Gmail collection.

One asyncio task wakes every GMAIL_SYNC_INTERVAL_MINUTES and syncs each
connected organization. It is in-process, like the processing queue: an SME
mailbox does not need a distributed scheduler.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.database import get_database
from app.core.errors import AppError
from app.integrations.ingestion.gmail_client import GmailClient
from app.repositories.channels import ChannelConnectionRepository
from app.repositories.quotations import QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.services.channels.gmail_sync import PROVIDER, Enqueue, run_gmail_sync
from app.services.storage.base import StorageBackend
from app.services.storage.local import get_storage

logger = logging.getLogger(__name__)


async def sync_all_gmail(
    *,
    database: Any,
    client: GmailClient,
    storage: StorageBackend,
    enqueue: Optional[Enqueue],
) -> dict[str, int]:
    """Sync every connected mailbox. A failure in one organization never stops the rest."""
    channels = ChannelConnectionRepository(database)
    summary = {"organizations": 0, "imported": 0, "failed": 0}
    for connection in await channels.list_active(PROVIDER):
        organization_id = str(connection["organization_id"])
        summary["organizations"] += 1
        try:
            result = await run_gmail_sync(
                organization_id=organization_id,
                client=client,
                channels=channels,
                quotations=QuotationRepository(database),
                suppliers=SupplierRepository(database),
                storage=storage,
                enqueue=enqueue,
            )
            summary["imported"] += result["documents_imported"]
        except AppError as exc:
            summary["failed"] += 1
            logger.warning("Gmail sync failed for organization %s: %s", organization_id, exc.message)
        except Exception:
            summary["failed"] += 1
            logger.exception("Unexpected Gmail sync failure for organization %s", organization_id)
    return summary


class ChannelScheduler:
    def __init__(self, interval_minutes: Optional[int] = None):
        self.interval_minutes = (
            settings.GMAIL_SYNC_INTERVAL_MINUTES if interval_minutes is None else interval_minutes
        )
        self._task: Optional[asyncio.Task] = None

    @property
    def enabled(self) -> bool:
        return self.interval_minutes > 0 and settings.google_configured

    async def start(self) -> None:
        if not self.enabled:
            logger.info(
                "Automatic Gmail collection is off (interval=%s min, Google configured=%s)",
                self.interval_minutes,
                settings.google_configured,
            )
            return
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="gmail-scheduler")
            logger.info("Automatic Gmail collection every %s min", self.interval_minutes)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _loop(self) -> None:
        from app.workers.processing import get_processing_queue

        while True:
            await asyncio.sleep(self.interval_minutes * 60)
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    summary = await sync_all_gmail(
                        database=get_database(),
                        client=GmailClient(http),
                        storage=get_storage(),
                        enqueue=get_processing_queue().enqueue,
                    )
                logger.info("Scheduled Gmail collection: %s", summary)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduled Gmail collection crashed; retrying next interval")


_scheduler: Optional[ChannelScheduler] = None


def get_channel_scheduler() -> ChannelScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ChannelScheduler()
    return _scheduler
