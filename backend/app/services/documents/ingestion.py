"""Ingestion service.

Manual upload, Gmail and WhatsApp all call `ingest_document`. There is exactly
one path from "bytes arrived" to "quotation record queued for processing", so
adding a channel later means writing an adapter that calls this function - not
duplicating the pipeline.

    Manual Upload ─┐
    Gmail ─────────┼──> ingest_document() ──> processing pipeline
    WhatsApp ──────┘
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.errors import ValidationError
from app.repositories.quotations import QuotationRepository
from app.schemas.common import ProcessingStatus, SourceType
from app.services.documents.detection import detect_document_type, is_allowed_upload
from app.services.storage.base import StorageBackend

logger = logging.getLogger(__name__)


@dataclass
class IngestionPayload:
    """A source-agnostic description of an incoming document."""

    data: bytes
    filename: str
    mime_type: Optional[str] = None
    source_type: SourceType = SourceType.MANUAL_UPLOAD
    external_reference: Optional[str] = None
    supplier_id: Optional[str] = None
    procurement_request_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


async def ingest_document(
    payload: IngestionPayload,
    *,
    organization_id: str,
    uploaded_by: Optional[str],
    repository: QuotationRepository,
    storage: StorageBackend,
) -> dict[str, Any]:
    """Validate, store the original file, and create the quotation record.

    Returns the created quotation. Processing is NOT performed here - the
    caller queues it, so an upload responds immediately.
    """
    if not payload.data:
        raise ValidationError("Uploaded file is empty.")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(payload.data) > max_bytes:
        raise ValidationError(
            f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit "
            f"({len(payload.data) / 1024 / 1024:.1f} MB)."
        )

    if not is_allowed_upload(payload.filename, payload.mime_type):
        raise ValidationError(
            f"Unsupported file type '{payload.filename}'. "
            "Supported formats: PDF, Excel (.xlsx/.xls), CSV, PNG, JPG."
        )

    document_type = detect_document_type(payload.data, payload.filename, payload.mime_type)

    # The original file is stored outside MongoDB; only the key is persisted.
    stored = await storage.save(
        payload.data,
        filename=payload.filename,
        prefix=f"quotations/{organization_id}",
        content_type=payload.mime_type,
    )

    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "source": {
            "type": payload.source_type.value,
            "original_filename": payload.filename,
            "mime_type": payload.mime_type,
            "size_bytes": len(payload.data),
            "storage_key": stored.key,
            "storage_backend": stored.backend,
            "external_reference": payload.external_reference,
            "metadata": payload.metadata or {},
        },
        "document_type": document_type.value,
        "processing_status": ProcessingStatus.UPLOADED.value,
        "supplier_id": _oid(payload.supplier_id),
        "procurement_request_id": _oid(payload.procurement_request_id),
        "supplier_name": None,
        "raw_content": None,
        "ai_extraction": None,
        "validation": None,
        "normalized_data": None,
        "effective_data": None,
        "match_result": None,
        "confidence": {},
        "user_corrections": [],
        "processing_history": [
            {
                "status": ProcessingStatus.UPLOADED.value,
                "message": f"Received '{payload.filename}' via {payload.source_type.value}.",
                "at": now,
                "details": {"size_bytes": len(payload.data), "document_type": document_type.value},
            }
        ],
        "uploaded_by": _oid(uploaded_by),
        "created_at": now,
    }

    quotation = await repository.create(organization_id, record)
    logger.info(
        "Ingested %s (%s) as quotation %s",
        payload.filename,
        payload.source_type.value,
        quotation.get("id"),
    )
    return quotation


def _oid(value: Optional[str]):
    from app.repositories.base import maybe_object_id

    return maybe_object_id(value)
