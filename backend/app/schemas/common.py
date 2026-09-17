"""Shared schema primitives."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Generic, List, TypeVar

from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

T = TypeVar("T")


def _to_str_id(v: Any) -> Any:
    if isinstance(v, ObjectId):
        return str(v)
    return v


# A MongoDB ObjectId rendered as a plain string in every API response.
PyObjectId = Annotated[str, BeforeValidator(_to_str_id)]


class APIModel(BaseModel):
    """Base for all API-facing models."""

    model_config = ConfigDict(
        populate_by_name=True,
        arbitrary_types_allowed=True,
        json_encoders={ObjectId: str, datetime: lambda d: d.isoformat()},
    )


class Paginated(APIModel, Generic[T]):
    items: List[T]
    total: int
    page: int = 1
    page_size: int = 50


class UserRole(str, Enum):
    ADMIN = "admin"
    PROCUREMENT_MANAGER = "procurement_manager"
    MEMBER = "member"


class SourceType(str, Enum):
    """Every ingestion channel funnels into the same document pipeline."""

    MANUAL_UPLOAD = "manual_upload"
    EMAIL = "email"        # future: Gmail ingestion
    WHATSAPP = "whatsapp"  # future: WhatsApp Business ingestion
    API = "api"


class DocumentType(str, Enum):
    PDF_DIGITAL = "pdf_digital"
    PDF_SCANNED = "pdf_scanned"
    IMAGE = "image"
    EXCEL = "excel"
    CSV = "csv"
    TEXT = "text"
    UNKNOWN = "unknown"


class ProcessingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    EXTRACTING = "EXTRACTING"
    AI_EXTRACTING = "AI_EXTRACTING"
    NORMALIZING = "NORMALIZING"
    COMPLETED = "COMPLETED"
    REQUIRES_REVIEW = "REQUIRES_REVIEW"
    FAILED = "FAILED"


class ProcurementStatus(str, Enum):
    DRAFT = "draft"
    OPEN = "open"
    COMPARING = "comparing"
    AWARDED = "awarded"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class MatchConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ProcessingEvent(APIModel):
    """One entry of the append-only processing history."""

    status: ProcessingStatus
    message: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now())
    details: dict[str, Any] = Field(default_factory=dict)
