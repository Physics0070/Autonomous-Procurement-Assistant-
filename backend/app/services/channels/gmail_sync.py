"""Gmail -> the shared ingestion pipeline.

Each sync lists messages matching the configured search and hands every
supported attachment - or, when a message has none, its plain-text body - to
the same ingest function manual upload uses.

Deduplication key: Gmail message id + MIME partId. Gmail's attachmentId changes
between fetches, so it cannot be used.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt_secret
from app.core.errors import AppError, ConflictError, UpstreamError, ValidationError
from app.integrations.ingestion.gmail_client import (
    GmailAPIError,
    GmailAuthError,
    GmailClient,
    decode_base64url,
    extract_plain_body,
    header,
    iter_parts,
    parse_sender_email,
)
from app.repositories.channels import ChannelConnectionRepository
from app.repositories.quotations import QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import SourceType
from app.services.documents.detection import ALLOWED_EXTENSIONS
from app.services.documents.ingestion import IngestionPayload, ingest_document_once
from app.services.storage.base import StorageBackend

Enqueue = Callable[[str, str], Awaitable[None]]

PROVIDER = "gmail"
RECONNECT_MESSAGE = (
    "Gmail access has expired or was revoked. Reconnect Gmail to resume collecting quotations."
)

# A .txt attachment is rarely a quotation; email bodies are handled separately.
ATTACHMENT_EXTENSIONS = ALLOWED_EXTENSIONS - {".txt"}
QUOTATION_KEYWORDS = (
    "quotation", "quote", "rfq", "price list", "rate list", "proforma", "कोटेशन", "भाव",
)


@dataclass
class GmailSyncResult:
    messages_scanned: int = 0
    documents_imported: int = 0
    duplicates_skipped: int = 0
    attachments_ignored: int = 0
    errors: list[str] = field(default_factory=list)
    quotation_ids: list[str] = field(default_factory=list)
    synced_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Context:
    organization_id: str
    client: GmailClient
    access_token: str
    quotations: QuotationRepository
    suppliers: SupplierRepository
    storage: StorageBackend
    enqueue: Enqueue
    mailbox: str
    result: GmailSyncResult


async def sync_gmail(
    *,
    organization_id: str,
    connection: dict[str, Any],
    client: GmailClient,
    quotations: QuotationRepository,
    suppliers: SupplierRepository,
    storage: StorageBackend,
    enqueue: Enqueue,
    query: str,
    max_messages: int,
) -> GmailSyncResult:
    """Import new quotations from one mailbox.

    Raises GmailAuthError when the stored grant no longer works. Any other
    per-message failure is recorded and the sync carries on.
    """
    result = GmailSyncResult()
    access_token = await client.refresh_access_token(
        decrypt_secret(connection["encrypted_refresh_token"])
    )
    context = _Context(
        organization_id=organization_id,
        client=client,
        access_token=access_token,
        quotations=quotations,
        suppliers=suppliers,
        storage=storage,
        enqueue=enqueue,
        mailbox=(connection.get("account_email") or "").lower(),
        result=result,
    )

    for message_id in await client.list_message_ids(access_token, query, max_messages):
        result.messages_scanned += 1
        try:
            message = await client.get_message(access_token, message_id)
            await _import_message(message, context)
        except GmailAuthError:
            raise
        except (AppError, GmailAPIError) as exc:
            result.errors.append(f"{message_id}: {exc}")

    result.synced_at = datetime.now(timezone.utc).isoformat()
    return result


async def _import_message(message: dict[str, Any], context: _Context) -> None:
    message_id = message["id"]
    subject = header(message, "Subject") or ""
    from_header = header(message, "From") or ""
    sender = parse_sender_email(from_header)
    if sender and sender == context.mailbox:
        return  # our own outgoing mail (such as RFQs) is not a supplier quotation

    supplier = (
        await context.suppliers.find_by_email(context.organization_id, sender) if sender else None
    )
    supplier_id = supplier["id"] if supplier else None
    received_at = header(message, "Date")
    metadata = {
        "channel": "gmail",
        "gmail_message_id": message_id,
        "gmail_thread_id": message.get("threadId"),
        "sender": from_header,
        "sender_email": sender,
        "subject": subject,
        "received_at": received_at,
        "mailbox": context.mailbox,
    }

    had_attachment = False
    for part in iter_parts(message.get("payload") or {}):
        filename = part.get("filename") or ""
        if not filename or _is_inline(part):
            continue
        if os.path.splitext(filename)[1].lower() not in ATTACHMENT_EXTENSIONS:
            context.result.attachments_ignored += 1
            continue
        body = part.get("body") or {}
        if body.get("attachmentId"):
            data = await context.client.get_attachment(
                context.access_token, message_id, body["attachmentId"]
            )
        elif body.get("data"):
            data = decode_base64url(body["data"])
        else:
            continue
        had_attachment = True
        await _ingest(
            IngestionPayload(
                data=data,
                filename=filename,
                mime_type=part.get("mimeType"),
                source_type=SourceType.EMAIL,
                external_reference=f"gmail:{message_id}:{part.get('partId')}",
                supplier_id=supplier_id,
                metadata=metadata,
            ),
            context,
        )

    if had_attachment:
        return

    text = extract_plain_body(message)
    if not text or not _looks_like_quotation(subject, text):
        return
    document = f"From: {from_header}\nSubject: {subject}\nDate: {received_at}\n\n{text}\n"
    await _ingest(
        IngestionPayload(
            data=document.encode("utf-8"),
            filename=f"email-{message_id}.txt",
            mime_type="text/plain",
            source_type=SourceType.EMAIL,
            external_reference=f"gmail:{message_id}:body",
            supplier_id=supplier_id,
            metadata={**metadata, "extracted_from": "email_body"},
        ),
        context,
    )


async def _ingest(payload: IngestionPayload, context: _Context) -> None:
    quotation, created = await ingest_document_once(
        payload,
        organization_id=context.organization_id,
        uploaded_by=None,
        repository=context.quotations,
        storage=context.storage,
    )
    if not created:
        context.result.duplicates_skipped += 1
        return
    quotation_id = str(quotation["id"])
    context.result.documents_imported += 1
    context.result.quotation_ids.append(quotation_id)
    await context.enqueue(context.organization_id, quotation_id)


def _is_inline(part: dict[str, Any]) -> bool:
    """Signature logos and embedded images are inline parts, not attachments."""
    for item in part.get("headers") or []:
        if str(item.get("name", "")).lower() == "content-disposition":
            return str(item.get("value", "")).lower().startswith("inline")
    return False


def _looks_like_quotation(subject: str, body: str) -> bool:
    text = f"{subject}\n{body}".lower()
    return any(keyword in text for keyword in QUOTATION_KEYWORDS)


async def run_gmail_sync(
    *,
    organization_id: str,
    client: GmailClient,
    channels: ChannelConnectionRepository,
    quotations: QuotationRepository,
    suppliers: SupplierRepository,
    storage: StorageBackend,
    enqueue: Enqueue,
) -> dict[str, Any]:
    """Sync one organization's mailbox and record the outcome on its connection.

    Shared by the "Sync now" endpoint and the background scheduler. Auth
    failures raise ConflictError (409), never an auth error, so a revoked Google
    grant can't be mistaken for an expired app session.
    """
    connection = await channels.get_for_provider(organization_id, PROVIDER)
    if connection is None:
        raise ValidationError("Gmail is not connected for this organization.")
    if connection.get("status") != "connected":
        raise ConflictError(RECONNECT_MESSAGE)

    try:
        result = await sync_gmail(
            organization_id=organization_id,
            connection=connection,
            client=client,
            quotations=quotations,
            suppliers=suppliers,
            storage=storage,
            enqueue=enqueue,
            query=settings.GMAIL_SYNC_QUERY,
            max_messages=settings.GMAIL_MAX_MESSAGES_PER_SYNC,
        )
    except (GmailAuthError, TokenDecryptionError) as exc:
        await channels.update_status(
            organization_id,
            PROVIDER,
            {"status": "reauthorization_required", "last_error": f"Reconnect Gmail: {exc}"},
        )
        raise ConflictError(RECONNECT_MESSAGE) from exc
    except GmailAPIError as exc:
        await channels.update_status(organization_id, PROVIDER, {"last_error": str(exc)})
        raise UpstreamError(f"Gmail could not be reached: {exc}") from exc

    await channels.update_status(
        organization_id,
        PROVIDER,
        {
            "last_synced_at": datetime.now(timezone.utc),
            "last_result": result.as_dict(),
            "last_error": "; ".join(result.errors[:3]) or None,
        },
    )
    return result.as_dict()
