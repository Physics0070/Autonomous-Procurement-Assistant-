"""Ingestion channel abstraction, and WhatsApp as documented future work.

Every channel converges on the same ingestion service and therefore the same
document pipeline, so adding one means fetching bytes - never duplicating
extraction, AI, normalization or comparison logic.

    Gmail attachment ──┐
    WhatsApp media ────┼──> IngestionPayload ──> ingest_document_once() ──> pipeline
    Manual upload ─────┘  (manual upload uses ingest_document directly)

Gmail is implemented in `app/services/channels/gmail_sync.py`. WhatsApp is
scoped by the synopsis as future support and stays inert: it needs the official
Meta WhatsApp Business Cloud API (verified business, phone number id, permanent
token, public HTTPS webhook). Unofficial libraries are not an acceptable route.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.core.errors import ConfigurationError
from app.repositories.quotations import QuotationRepository
from app.schemas.common import SourceType
from app.services.documents.ingestion import IngestionPayload, ingest_document_once
from app.services.storage.base import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class InboundMessage:
    """Channel-agnostic description of an inbound message with attachments."""

    external_id: str
    sender: Optional[str]
    subject: Optional[str]
    body: Optional[str]
    attachments: list[tuple[str, bytes, Optional[str]]]  # (filename, data, mime)
    received_at: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class IngestionChannel(abc.ABC):
    """A source of inbound procurement documents."""

    source_type: SourceType = SourceType.API
    name: str = "abstract"

    @abc.abstractmethod
    def is_configured(self) -> bool:
        ...

    @abc.abstractmethod
    def configuration_error(self) -> Optional[str]:
        ...

    @abc.abstractmethod
    async def fetch(self, since: Optional[str] = None) -> Iterable[InboundMessage]:
        ...

    async def ingest_all(
        self,
        *,
        organization_id: str,
        repository: QuotationRepository,
        storage: StorageBackend,
    ) -> list[dict[str, Any]]:
        """Shared funnel: every channel reaches the pipeline through here."""
        if not self.is_configured():
            raise ConfigurationError(self.configuration_error() or f"{self.name} is not configured.")

        created = []
        for message in await self.fetch():
            for index, (filename, data, mime) in enumerate(message.attachments, start=1):
                quotation, is_new = await ingest_document_once(
                    IngestionPayload(
                        data=data,
                        filename=filename,
                        mime_type=mime,
                        source_type=self.source_type,
                        # One reference per attachment; the message id alone
                        # would collide with the unique channel-reference index.
                        external_reference=f"{self.name}:{message.external_id}:{index}",
                        metadata={
                            "channel": self.name,
                            "sender": message.sender,
                            "subject": message.subject,
                            "received_at": message.received_at,
                            **(message.metadata or {}),
                        },
                    ),
                    organization_id=organization_id,
                    uploaded_by=None,
                    repository=repository,
                    storage=storage,
                )
                if is_new:
                    created.append(quotation)
        return created


class WhatsAppIngestionChannel(IngestionChannel):
    """Planned: receive WhatsApp Business Cloud API webhooks and ingest media.

        Webhook -> media id -> media bytes -> IngestionPayload
    """

    source_type = SourceType.WHATSAPP
    name = "whatsapp"

    def __init__(self, credentials: Optional[dict[str, Any]] = None):
        self.credentials = credentials or {}

    def is_configured(self) -> bool:
        return False

    def configuration_error(self) -> Optional[str]:
        return (
            "WhatsApp ingestion is not implemented yet. It requires the official Meta "
            "WhatsApp Business Cloud API (phone number id, permanent access token and a "
            "verified webhook endpoint). The adapter is wired to the shared ingestion "
            "service so enabling it needs no pipeline changes."
        )

    async def fetch(self, since: Optional[str] = None) -> Iterable[InboundMessage]:
        raise ConfigurationError(self.configuration_error())


# Gmail is implemented in app/services/channels/gmail_sync.py (Phase 3).
AVAILABLE_CHANNELS: dict[str, type[IngestionChannel]] = {
    "whatsapp": WhatsAppIngestionChannel,
}
