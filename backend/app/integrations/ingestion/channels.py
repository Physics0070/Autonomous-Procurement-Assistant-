"""Future ingestion channels - architecture, not implementation.

Both Gmail and WhatsApp converge on the SAME ingestion service and therefore
the SAME document pipeline. These adapters exist so that adding a channel is
a matter of fetching bytes and calling `ingest_document`, with zero duplication
of extraction, AI, normalization or comparison logic.

    Gmail attachment ──┐
    WhatsApp media ────┼──> IngestionPayload ──> ingest_document() ──> pipeline
    Manual upload ─────┘

Nothing below performs network calls. They are deliberately inert until the
corresponding credentials and provider onboarding exist:
  * Gmail    - OAuth client + refresh token, Gmail API readonly scope
  * WhatsApp - Meta WhatsApp Business Cloud API (phone number id + token);
               unofficial libraries are not an acceptable route for a business
               product, so this stays unimplemented until the official API is
               provisioned.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.core.errors import ConfigurationError
from app.repositories.quotations import QuotationRepository
from app.schemas.common import SourceType
from app.services.documents.ingestion import IngestionPayload, ingest_document
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
            for filename, data, mime in message.attachments:
                quotation = await ingest_document(
                    IngestionPayload(
                        data=data,
                        filename=filename,
                        mime_type=mime,
                        source_type=self.source_type,
                        external_reference=message.external_id,
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
                created.append(quotation)
        return created


class GmailIngestionChannel(IngestionChannel):
    """Planned: poll a mailbox and ingest quotation attachments.

        Gmail API -> message list -> attachment bytes -> IngestionPayload
    """

    source_type = SourceType.EMAIL
    name = "gmail"

    def __init__(self, credentials: Optional[dict[str, Any]] = None):
        self.credentials = credentials or {}

    def is_configured(self) -> bool:
        return False

    def configuration_error(self) -> Optional[str]:
        return (
            "Gmail ingestion is not implemented yet. It requires a Google OAuth client, "
            "a stored refresh token and the gmail.readonly scope. The adapter is wired to "
            "the shared ingestion service so enabling it needs no pipeline changes."
        )

    async def fetch(self, since: Optional[str] = None) -> Iterable[InboundMessage]:
        raise ConfigurationError(self.configuration_error())


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


AVAILABLE_CHANNELS: dict[str, type[IngestionChannel]] = {
    "gmail": GmailIngestionChannel,
    "whatsapp": WhatsAppIngestionChannel,
}
