"""The common raw representation.

PDF, Excel, images and (later) Gmail / WhatsApp payloads all converge on
ProcessedDocument before anything downstream touches them. Nothing after this
point is allowed to care where the bytes came from.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from pydantic import Field

from app.schemas.common import APIModel, DocumentType, SourceType


class ExtractedTable(APIModel):
    """A table lifted out of a PDF page or a spreadsheet sheet."""

    name: Optional[str] = None          # sheet name / table label
    page: Optional[int] = None          # 1-based page for PDFs
    headers: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    column_count: int = 0
    source: str = "unknown"             # pdf_table | excel_sheet | csv


class PageText(APIModel):
    page: int
    text: str = ""
    char_count: int = 0
    method: str = "native"              # native | ocr
    ocr_confidence: Optional[float] = None


class ProcessedDocument(APIModel):
    """The common raw representation handed to the AI extraction stage."""

    quotation_id: Optional[str] = None
    source_type: SourceType = SourceType.MANUAL_UPLOAD
    document_type: DocumentType = DocumentType.UNKNOWN

    raw_text: str = ""
    pages: List[PageText] = Field(default_factory=list)
    tables: List[ExtractedTable] = Field(default_factory=list)

    detected_language: Optional[str] = None
    ocr_used: bool = False
    ocr_engine: Optional[str] = None
    ocr_confidence: Optional[float] = None

    extraction_errors: List[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def char_count(self) -> int:
        return len(self.raw_text)

    def text_for_ai(self, max_chars: int = 60000) -> str:
        """Flatten text + tables into a single prompt-ready block."""
        parts: List[str] = []
        if self.raw_text.strip():
            parts.append("===== DOCUMENT TEXT =====")
            parts.append(self.raw_text.strip())
        for idx, table in enumerate(self.tables):
            label = table.name or f"Table {idx + 1}"
            loc = f" (page {table.page})" if table.page else ""
            parts.append(f"\n===== TABLE: {label}{loc} =====")
            if table.headers:
                parts.append(" | ".join(str(h) for h in table.headers))
                parts.append("-" * 40)
            for row in table.rows[:200]:
                parts.append(" | ".join("" if c is None else str(c) for c in row))
        blob = "\n".join(parts)
        if len(blob) > max_chars:
            blob = blob[:max_chars] + "\n...[truncated]"
        return blob
