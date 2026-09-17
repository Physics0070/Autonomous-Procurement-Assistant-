"""Document type detection from bytes + filename + MIME."""
from __future__ import annotations

import os
from typing import Optional

from app.schemas.common import DocumentType

PDF_MIMES = {"application/pdf"}
EXCEL_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.oasis.opendocument.spreadsheet",
}
IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/tiff", "image/bmp", "image/webp"}
CSV_MIMES = {"text/csv", "application/csv"}

PDF_EXT = {".pdf"}
EXCEL_EXT = {".xlsx", ".xls", ".xlsm", ".ods"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
CSV_EXT = {".csv", ".tsv"}
# Plain text carries quotations written directly in an email body.
TEXT_EXT = {".txt"}

ALLOWED_EXTENSIONS = PDF_EXT | EXCEL_EXT | IMAGE_EXT | CSV_EXT | TEXT_EXT


def detect_document_type(
    data: bytes, filename: Optional[str] = None, mime_type: Optional[str] = None
) -> DocumentType:
    """Magic bytes first, then MIME, then extension."""
    head = data[:8] if data else b""

    if head.startswith(b"%PDF"):
        return DocumentType.PDF_DIGITAL  # refined to PDF_SCANNED after text probing
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8\xff") or head[:2] in (b"BM",):
        return DocumentType.IMAGE
    if head.startswith(b"PK\x03\x04"):
        # xlsx/ods are zip containers; distinguish by extension
        ext = os.path.splitext(filename or "")[1].lower()
        if ext in EXCEL_EXT:
            return DocumentType.EXCEL
        return DocumentType.EXCEL
    if head.startswith(b"\xd0\xcf\x11\xe0"):  # legacy OLE (.xls)
        return DocumentType.EXCEL

    mime = (mime_type or "").lower().split(";")[0].strip()
    if mime in PDF_MIMES:
        return DocumentType.PDF_DIGITAL
    if mime in EXCEL_MIMES:
        return DocumentType.EXCEL
    if mime in IMAGE_MIMES:
        return DocumentType.IMAGE
    if mime in CSV_MIMES:
        return DocumentType.CSV

    ext = os.path.splitext(filename or "")[1].lower()
    if ext in PDF_EXT:
        return DocumentType.PDF_DIGITAL
    if ext in EXCEL_EXT:
        return DocumentType.EXCEL
    if ext in IMAGE_EXT:
        return DocumentType.IMAGE
    if ext in CSV_EXT:
        return DocumentType.CSV
    if ext in {".txt", ".md"}:
        return DocumentType.TEXT
    return DocumentType.UNKNOWN


def is_allowed_upload(filename: Optional[str], mime_type: Optional[str]) -> bool:
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in ALLOWED_EXTENSIONS:
        return True
    mime = (mime_type or "").lower().split(";")[0].strip()
    return mime in (PDF_MIMES | EXCEL_MIMES | IMAGE_MIMES | CSV_MIMES | {"text/plain"})


def detect_language(text: str) -> str:
    """Very small script-based language hint (no extra dependency).

    Returns an ISO-ish code. Deliberately conservative - it hints at script,
    which is what matters for OCR language selection and multilingual notes.
    """
    if not text:
        return "unknown"
    devanagari = sum(1 for ch in text if "ऀ" <= ch <= "ॿ")
    gujarati = sum(1 for ch in text if "઀" <= ch <= "૿")
    tamil = sum(1 for ch in text if "஀" <= ch <= "௿")
    telugu = sum(1 for ch in text if "ఀ" <= ch <= "౿")
    bengali = sum(1 for ch in text if "ঀ" <= ch <= "৿")
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    scores = {"hi": devanagari, "gu": gujarati, "ta": tamil, "te": telugu, "bn": bengali, "en": latin}
    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        return "unknown"
    non_latin = sum(v for k, v in scores.items() if k != "en")
    # Indian SME quotations routinely carry only a handful of regional-script
    # words (a product name, a header) inside otherwise-Latin text. A small
    # absolute count is therefore enough to call the document mixed-script,
    # which is what drives OCR language selection.
    if non_latin >= 8 or (non_latin > 0 and non_latin >= 0.05 * max(latin, 1)):
        mixed = max((k for k in scores if k != "en"), key=lambda k: scores[k])
        return f"{mixed}+en" if latin > 0 else mixed
    return "en" if latin else best
