"""Single entry point for turning raw bytes into a ProcessedDocument.

Manual upload, Gmail and WhatsApp all call this. There is exactly one
implementation of document processing in the system.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.schemas.common import DocumentType, SourceType
from app.schemas.document import PageText, ProcessedDocument
from app.services.documents.detection import detect_document_type, detect_language
from app.services.documents.extractors.excel import extract_csv, extract_excel
from app.services.documents.extractors.image import extract_image
from app.services.documents.extractors.pdf import extract_pdf

logger = logging.getLogger(__name__)


def process_document_sync(
    data: bytes,
    *,
    filename: str = "",
    mime_type: Optional[str] = None,
    source_type: SourceType = SourceType.MANUAL_UPLOAD,
    quotation_id: Optional[str] = None,
) -> ProcessedDocument:
    doc_type = detect_document_type(data, filename, mime_type)

    if doc_type in (DocumentType.PDF_DIGITAL, DocumentType.PDF_SCANNED):
        doc = extract_pdf(data, source_type=source_type)
    elif doc_type == DocumentType.EXCEL:
        doc = extract_excel(data, filename=filename, source_type=source_type)
    elif doc_type == DocumentType.CSV:
        doc = extract_csv(data, filename=filename, source_type=source_type)
    elif doc_type == DocumentType.IMAGE:
        doc = extract_image(data, filename=filename, source_type=source_type)
    elif doc_type == DocumentType.TEXT:
        text = _decode(data)
        doc = ProcessedDocument(
            source_type=source_type,
            document_type=DocumentType.TEXT,
            raw_text=text,
            pages=[PageText(page=1, text=text, char_count=len(text))],
            detected_language=detect_language(text),
        )
    else:
        doc = ProcessedDocument(source_type=source_type, document_type=DocumentType.UNKNOWN)
        doc.extraction_errors.append(
            f"Unsupported document type for '{filename}' (mime={mime_type})."
        )

    doc.quotation_id = quotation_id
    doc.metadata.setdefault("source_filename", filename)
    doc.metadata.setdefault("mime_type", mime_type)
    doc.metadata["byte_size"] = len(data)
    doc.metadata["detected_type"] = doc.document_type.value
    doc.metadata["char_count"] = len(doc.raw_text)

    if not doc.raw_text.strip() and not doc.tables and not doc.extraction_errors:
        doc.extraction_errors.append("No text or tables could be extracted from this document.")
    return doc


async def process_document(
    data: bytes,
    *,
    filename: str = "",
    mime_type: Optional[str] = None,
    source_type: SourceType = SourceType.MANUAL_UPLOAD,
    quotation_id: Optional[str] = None,
) -> ProcessedDocument:
    """Async wrapper - extraction is CPU-bound, so it runs off the event loop."""
    return await asyncio.to_thread(
        process_document_sync,
        data,
        filename=filename,
        mime_type=mime_type,
        source_type=source_type,
        quotation_id=quotation_id,
    )


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
