"""Document upload and ingestion endpoints.

Upload returns as soon as the file is stored and the record created; the
extraction/AI/normalization work happens on the background queue.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from app.api.deps import CurrentUser, quotation_repo, storage
from app.repositories.quotations import QuotationRepository
from app.schemas.common import ProcessingStatus, SourceType
from app.schemas.quotation import QuotationUploadResponse
from app.services.documents.ingestion import IngestionPayload, ingest_document
from app.services.documents.ocr import get_ocr_service
from app.services.storage.base import StorageBackend
from app.workers.processing import get_processing_queue

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=QuotationUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    context: CurrentUser,
    file: UploadFile = File(...),
    procurement_request_id: Optional[str] = Form(default=None),
    supplier_id: Optional[str] = Form(default=None),
    quotations: QuotationRepository = Depends(quotation_repo),
    store: StorageBackend = Depends(storage),
) -> QuotationUploadResponse:
    data = await file.read()
    quotation = await ingest_document(
        IngestionPayload(
            data=data,
            filename=file.filename or "upload",
            mime_type=file.content_type,
            source_type=SourceType.MANUAL_UPLOAD,
            supplier_id=supplier_id or None,
            procurement_request_id=procurement_request_id or None,
            metadata={"uploaded_by_name": context.user.get("name")},
        ),
        organization_id=context.organization_id,
        uploaded_by=context.user_id,
        repository=quotations,
        storage=store,
    )

    await get_processing_queue().enqueue(context.organization_id, str(quotation["id"]))

    return QuotationUploadResponse(
        quotation_id=str(quotation["id"]),
        processing_status=ProcessingStatus.QUEUED,
        original_filename=file.filename,
        message="Uploaded. Extraction and normalization are running in the background.",
    )


@router.get("/capabilities")
async def capabilities(context: CurrentUser) -> dict:
    """What the deployment can actually do right now.

    The frontend uses this to tell users which features are degraded rather
    than silently producing worse results.
    """
    from app.integrations.ai.factory import get_ai_provider

    ocr = get_ocr_service()
    engine = ocr.select()
    provider = get_ai_provider()
    queue = get_processing_queue()

    return {
        "ocr": {
            "available": engine is not None,
            "engine": engine.name if engine else None,
            "engines_installed": ocr.available_engines(),
            "message": None if engine else "No OCR engine installed; scanned documents cannot be read.",
        },
        "ai": {
            "configured": provider.is_configured(),
            "provider": provider.name,
            "model": getattr(provider, "model", None),
            "message": provider.configuration_error(),
        },
        "supported_formats": ["pdf", "xlsx", "xls", "csv", "png", "jpg", "jpeg"],
        "queue": {"depth": queue.depth(), "in_flight": queue.in_flight()},
    }
