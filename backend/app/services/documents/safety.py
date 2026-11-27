"""Content checks every incoming file passes before it is stored, whichever channel it came through.

Files are never executed: PDFs are rendered by PyMuPDF, spreadsheets read as values by openpyxl/xlrd (macros are not
run), images decoded by Pillow. These checks refuse the active content those formats can carry, so a hostile file is
rejected at the door instead of sitting in storage. They are not an antivirus scan; see docs/RELEASE_READINESS.md.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Optional

from app.core.errors import ValidationError

MAX_UNPACKED_BYTES = 200 * 1024 * 1024   # an .xlsx that unpacks past this is a zip bomb, not a quotation
MAX_ZIP_MEMBERS = 5000
_PDF_ACTIVE = re.compile(rb"/(JavaScript|JS|Launch|RichMedia)\b")
# Attachments that are metadata, not payloads: the "Content Credentials" (C2PA) tag phones and Adobe tools add, and the
# XML/JSON data that e-invoices carry. Seen on 2 of the team's real quotations.
_BENIGN_ATTACHMENT = re.compile(r"^(content credentials|.*\.(xml|json|txt))$", re.IGNORECASE)
_PAYLOAD_MAGIC = (b"MZ", b"PK\x03\x04", b"\xd0\xcf\x11\xe0", b"%PDF", b"#!", b"\x7fELF", b"Rar!", b"7z\xbc\xaf")
_PDF_NAME_ESCAPE = re.compile(rb"#([0-9A-Fa-f]{2})")


def _refuse(reason: str) -> None:
    raise ValidationError(f"This file was refused for safety: {reason}. Save it again without that content and re-upload.")


def _check_zip(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return  # unreadable to every parser, so inert; processing marks it failed with a clear message
    members = archive.infolist()
    if len(members) > MAX_ZIP_MEMBERS or sum(m.file_size for m in members) > MAX_UNPACKED_BYTES:
        _refuse("the spreadsheet unpacks to an unreasonable size")
    if any(m.filename.lower().endswith("vbaproject.bin") or "activex" in m.filename.lower() for m in members):
        _refuse("the spreadsheet contains macros or ActiveX controls")


def _check_pdf(data: bytes) -> None:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return  # nothing can render it, so nothing in it can run; processing marks it failed with a clear message
    try:
        for index in range(doc.embfile_count()):
            name = doc.embfile_info(index).get("filename") or ""
            if not _BENIGN_ATTACHMENT.match(name) or doc.embfile_get(index)[:8].startswith(_PAYLOAD_MAGIC):
                _refuse("the PDF carries an attached file")
        for xref in range(1, doc.xref_length()):  # object streams are decompressed here, unlike a raw byte search
            source = doc.xref_object(xref, compressed=False).encode("latin-1", "replace")
            source = _PDF_NAME_ESCAPE.sub(lambda m: bytes([int(m.group(1), 16)]), source)  # /J#61vaScript
            if _PDF_ACTIVE.search(source):
                _refuse("the PDF contains scripts or launch actions")
    finally:
        doc.close()


def check_upload_safety(data: bytes, filename: Optional[str]) -> None:
    """Raise ValidationError for active or oversized content. Plain quotations pass untouched."""
    name = (filename or "").lower()
    if name.endswith((".xlsm", ".xlsb", ".xltm", ".xlam")):
        _refuse("macro-enabled Excel formats are not accepted")
    if data[:4] == b"%PDF":
        _check_pdf(data)
    elif data[:4] == b"PK\x03\x04":
        _check_zip(data)
    elif data[:4] == b"\xd0\xcf\x11\xe0" and (b"_VBA_PROJECT" in data or "_VBA_PROJECT".encode("utf-16-le") in data):
        _refuse("the spreadsheet contains macros")
