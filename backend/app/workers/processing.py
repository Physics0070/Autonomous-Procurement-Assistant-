"""In-process background processing queue.

An asyncio queue with a small pool of workers. Uploads return immediately and
processing happens off the request path.

This is deliberately NOT Celery/Redis/RabbitMQ: the workload is a handful of
documents per minute for an SME, and a distributed broker would be infrastructure
without a purpose. The interface (`enqueue`) is narrow enough that swapping in a
real broker later is a contained change.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.database import get_database
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import PriceHistoryRepository, QuotationRepository
from app.schemas.common import ProcessingStatus
from app.services.documents.pipeline import ProcessingPipeline
from app.services.storage.local import get_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingJob:
    organization_id: str
    quotation_id: str


class ProcessingQueue:
    def __init__(self, concurrency: Optional[int] = None):
        self.concurrency = concurrency or settings.PROCESSING_WORKER_CONCURRENCY
        self._queue: asyncio.Queue[ProcessingJob] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._running = False
        self._in_flight: set[str] = set()

    # -- lifecycle ------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i + 1), name=f"processing-worker-{i + 1}")
            for i in range(self.concurrency)
        ]
        logger.info("Processing queue started with %d worker(s)", self.concurrency)

    async def stop(self) -> None:
        self._running = False
        for task in self._workers:
            task.cancel()
        for task in self._workers:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: B014
                pass
        self._workers.clear()
        logger.info("Processing queue stopped")

    # -- api ------------------------------------------------------------
    async def enqueue(self, organization_id: str, quotation_id: str) -> None:
        job = ProcessingJob(organization_id=organization_id, quotation_id=quotation_id)
        if quotation_id in self._in_flight:
            logger.debug("Quotation %s is already queued; skipping duplicate", quotation_id)
            return
        self._in_flight.add(quotation_id)
        await self._queue.put(job)
        # Mark QUEUED immediately so the UI reflects reality before a worker picks it up.
        try:
            repository = QuotationRepository(get_database())
            await repository.set_status(
                organization_id,
                quotation_id,
                ProcessingStatus.QUEUED.value,
                message="Queued for processing.",
            )
        except Exception as exc:
            logger.warning("Could not mark quotation %s as QUEUED: %s", quotation_id, exc)

    def depth(self) -> int:
        return self._queue.qsize()

    def in_flight(self) -> int:
        return len(self._in_flight)

    # -- internals ------------------------------------------------------
    async def _worker(self, index: int) -> None:
        while self._running:
            try:
                job = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._process(job)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Worker %d failed on quotation %s", index, job.quotation_id)
            finally:
                self._in_flight.discard(job.quotation_id)
                self._queue.task_done()

    async def _process(self, job: ProcessingJob) -> None:
        database = get_database()
        pipeline = ProcessingPipeline(
            quotations=QuotationRepository(database),
            suppliers=__import__(
                "app.repositories.suppliers", fromlist=["SupplierRepository"]
            ).SupplierRepository(database),
            requests=ProcurementRequestRepository(database),
            price_history=PriceHistoryRepository(database),
            storage=get_storage(),
        )
        logger.info("Processing quotation %s", job.quotation_id)
        await pipeline.run(job.organization_id, job.quotation_id)

    async def wait_until_idle(self, timeout: float = 120.0) -> bool:
        """Block until the queue drains. Used by tests and the E2E script."""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


_queue: Optional[ProcessingQueue] = None


def get_processing_queue() -> ProcessingQueue:
    global _queue
    if _queue is None:
        _queue = ProcessingQueue()
    return _queue


async def recover_pending_jobs() -> int:
    """Re-queue work that was in flight when the process last stopped."""
    repository = QuotationRepository(get_database())
    pending = await repository.pending_processing(limit=100)
    queue = get_processing_queue()
    for row in pending:
        organization_id = row.get("organization_id")
        if organization_id:
            await queue.enqueue(str(organization_id), str(row["id"]))
    if pending:
        logger.info("Re-queued %d pending quotation(s) after restart", len(pending))
    return len(pending)
