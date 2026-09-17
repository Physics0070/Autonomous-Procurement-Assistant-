"""PDF extraction via PyMuPDF, with OCR only where it is actually needed."""
from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.schemas.common import DocumentType, SourceType
from app.schemas.document import ExtractedTable, PageText, ProcessedDocument
from app.services.documents.detection import detect_language
from app.services.documents.ocr import get_ocr_service

logger = logging.getLogger(__name__)


def extract_pdf(data: bytes, source_type: SourceType = SourceType.MANUAL_UPLOAD) -> ProcessedDocument:
    import fitz  # PyMuPDF

    doc = ProcessedDocument(source_type=source_type, document_type=DocumentType.PDF_DIGITAL)
    ocr_confidences: list[float] = []

    try:
        pdf = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        doc.extraction_errors.append(f"Failed to open PDF: {exc}")
        doc.document_type = DocumentType.UNKNOWN
        return doc

    try:
        doc.metadata.update(
            {
                "page_count": pdf.page_count,
                "pdf_metadata": {k: v for k, v in (pdf.metadata or {}).items() if v},
                "is_encrypted": pdf.is_encrypted,
            }
        )

        min_chars = settings.PDF_TEXT_MIN_CHARS_PER_PAGE
        ocr_service = get_ocr_service()
        pages_needing_ocr: list[int] = []

        # --- Pass 1: native text + tables (no OCR yet) ---
        for index in range(pdf.page_count):
            page = pdf[index]
            text = (page.get_text("text") or "").strip()
            doc.pages.append(
                PageText(page=index + 1, text=text, char_count=len(text), method="native")
            )
            if len(text) < min_chars:
                pages_needing_ocr.append(index)

            # PyMuPDF table detection (available in recent versions)
            try:
                finder = page.find_tables()
                for t_index, table in enumerate(getattr(finder, "tables", []) or []):
                    rows = table.extract() or []
                    if not rows:
                        continue
                    headers = [str(c) if c is not None else "" for c in rows[0]]
                    body = [[c for c in r] for r in rows[1:]]
                    doc.tables.append(
                        ExtractedTable(
                            name=f"page{index + 1}_table{t_index + 1}",
                            page=index + 1,
                            headers=headers,
                            rows=body,
                            row_count=len(body),
                            column_count=len(headers),
                            source="pdf_table",
                        )
                    )
            except Exception as exc:  # table finder is best-effort
                logger.debug("Table detection skipped on page %s: %s", index + 1, exc)

        native_chars = sum(p.char_count for p in doc.pages)
        doc.metadata["native_char_count"] = native_chars
        doc.metadata["pages_needing_ocr"] = [p + 1 for p in pages_needing_ocr]

        # --- Pass 2: OCR ONLY the pages that lacked usable text ---
        if pages_needing_ocr:
            lang_hint = detect_language("\n".join(p.text for p in doc.pages))
            engine = ocr_service.select()
            if engine is None:
                doc.extraction_errors.append(
                    f"{len(pages_needing_ocr)} page(s) appear scanned but no OCR engine is available."
                )
                doc.metadata["ocr_skipped_reason"] = "no_engine"
            else:
                for index in pages_needing_ocr:
                    try:
                        page = pdf[index]
                        # 2x zoom improves OCR accuracy substantially.
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        img_bytes = pix.tobytes("png")
                        result = ocr_service.run(img_bytes, lang=lang_hint)
                        if result.error:
                            doc.extraction_errors.append(f"OCR page {index + 1}: {result.error}")
                            continue
                        if result.text:
                            doc.pages[index] = PageText(
                                page=index + 1,
                                text=result.text,
                                char_count=len(result.text),
                                method="ocr",
                                ocr_confidence=result.confidence,
                            )
                            doc.ocr_used = True
                            doc.ocr_engine = result.engine
                            if result.confidence is not None:
                                ocr_confidences.append(result.confidence)
                    except Exception as exc:
                        doc.extraction_errors.append(f"OCR failed on page {index + 1}: {exc}")

        # A PDF whose text came predominantly from OCR is a scanned PDF.
        ocr_pages = sum(1 for p in doc.pages if p.method == "ocr")
        if ocr_pages and ocr_pages >= max(1, len(doc.pages) // 2):
            doc.document_type = DocumentType.PDF_SCANNED

        doc.raw_text = "\n\n".join(
            f"--- Page {p.page} ---\n{p.text}" for p in doc.pages if p.text.strip()
        )
        doc.detected_language = detect_language(doc.raw_text)
        if ocr_confidences:
            doc.ocr_confidence = sum(ocr_confidences) / len(ocr_confidences)
        doc.metadata["ocr_page_count"] = ocr_pages
        doc.metadata["table_count"] = len(doc.tables)
    finally:
        pdf.close()

    return doc
