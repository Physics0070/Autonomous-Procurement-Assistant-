from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import Field

from app.schemas.common import (
    APIModel,
    DocumentType,
    ProcessingEvent,
    ProcessingStatus,
    PyObjectId,
    SourceType,
)
from app.schemas.document import ProcessedDocument
from app.schemas.extraction import AIExtractionResult, ValidationReport
from app.schemas.normalized import MatchResult, NormalizedQuotation


class QuotationSource(APIModel):
    type: SourceType = SourceType.MANUAL_UPLOAD
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    storage_key: Optional[str] = None       # opaque key for the storage backend
    external_reference: Optional[str] = None  # gmail message id / whatsapp msg id
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfidenceSummary(APIModel):
    extraction: Optional[float] = None
    ocr: Optional[float] = None
    normalization: Optional[float] = None
    overall: Optional[float] = None


class UserCorrection(APIModel):
    """A user edit. Applied on top of - never into - the AI extraction."""

    path: str                      # dotted path inside normalized_data
    previous_value: Any = None
    new_value: Any = None
    corrected_by: Optional[str] = None
    corrected_at: Optional[datetime] = None
    note: Optional[str] = None


class QuotationListItem(APIModel):
    id: PyObjectId
    organization_id: PyObjectId
    source: QuotationSource
    document_type: DocumentType = DocumentType.UNKNOWN
    supplier_id: Optional[PyObjectId] = None
    supplier_name: Optional[str] = None
    procurement_request_id: Optional[PyObjectId] = None
    processing_status: ProcessingStatus
    total_amount: Optional[float] = None
    currency: str = "INR"
    item_count: int = 0
    requires_review: bool = False
    issue_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None


class QuotationDetail(QuotationListItem):
    """Full review payload: original -> raw -> AI -> normalized -> corrected."""

    raw_content: Optional[ProcessedDocument] = None
    ai_extraction: Optional[AIExtractionResult] = None
    validation: Optional[ValidationReport] = None
    normalized_data: Optional[NormalizedQuotation] = None
    effective_data: Optional[NormalizedQuotation] = None  # normalized + corrections
    match_result: Optional[MatchResult] = None
    confidence: ConfidenceSummary = Field(default_factory=ConfidenceSummary)
    user_corrections: List[UserCorrection] = Field(default_factory=list)
    processing_history: List[ProcessingEvent] = Field(default_factory=list)
    error: Optional[str] = None


class QuotationUploadResponse(APIModel):
    quotation_id: PyObjectId
    processing_status: ProcessingStatus
    original_filename: Optional[str] = None
    message: str = "Uploaded. Processing has been queued."


class CorrectionRequest(APIModel):
    """Corrections keyed by dotted path into normalized_data.

    Example: {"items.0.unit_price": 145.0, "delivery.delivery_days": 7}
    """

    corrections: dict[str, Any] = Field(default_factory=dict)
    note: Optional[str] = None


class QuotationLinkRequest(APIModel):
    procurement_request_id: Optional[str] = None
    supplier_id: Optional[str] = None
