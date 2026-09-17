"""Excel / CSV extraction.

Column names are never assumed. Every sheet is preserved as headers + rows, and
a readable text rendering is produced so the AI stage sees the same shape it
sees for PDFs.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any

from app.schemas.common import DocumentType, SourceType
from app.schemas.document import ExtractedTable, PageText, ProcessedDocument
from app.services.documents.detection import detect_language

logger = logging.getLogger(__name__)


def _clean_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if value.is_integer():
            return int(value)
        return round(value, 6)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, str):
        s = value.strip()
        return s or None
    return value


def _header_score(row: list[Any], following: list[list[Any]]) -> float:
    """Score how much a row looks like a table header.

    Real headers are wide (many populated cells), mostly textual, and followed
    by rows of similar width. A stray label/value pair near the top of the
    sheet scores badly on width, which is what keeps it from winning.
    """
    non_empty = [c for c in row if c not in (None, "")]
    if len(non_empty) < 2:
        return 0.0
    strings = sum(1 for c in non_empty if isinstance(c, str))
    string_ratio = strings / len(non_empty)
    if string_ratio < 0.6:
        return 0.0

    score = len(non_empty) * string_ratio

    # Reward headers whose following rows have a comparable width.
    sample = [r for r in following[:5] if any(c not in (None, "") for c in r)]
    if sample:
        widths = [len([c for c in r if c not in (None, "")]) for r in sample]
        avg_width = sum(widths) / len(widths)
        if avg_width >= len(non_empty) * 0.6:
            score *= 1.6
    else:
        score *= 0.5  # a "header" with nothing under it is not a header

    # Common procurement header vocabulary is a strong signal.
    keywords = {
        "description", "item", "material", "product", "qty", "quantity", "units",
        "unit", "uom", "rate", "price", "amount", "total", "tax", "gst", "sr",
        "s.no", "sno", "particulars", "hsn", "value", "discount",
    }
    hits = sum(1 for c in non_empty if isinstance(c, str) and c.strip().lower() in keywords)
    hits += sum(
        1
        for c in non_empty
        if isinstance(c, str) and any(k in c.strip().lower() for k in keywords)
    )
    score += hits * 2.0
    return score


def extract_excel(
    data: bytes, filename: str = "", source_type: SourceType = SourceType.MANUAL_UPLOAD
) -> ProcessedDocument:
    import pandas as pd

    doc = ProcessedDocument(source_type=source_type, document_type=DocumentType.EXCEL)
    text_blocks: list[str] = []

    try:
        # header=None: never assume the first row is the header.
        sheets: dict[str, Any] = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, dtype=object)
    except Exception as exc:
        doc.extraction_errors.append(f"Failed to read workbook: {exc}")
        return doc

    doc.metadata["sheet_names"] = list(sheets.keys())
    doc.metadata["sheet_count"] = len(sheets)

    for page_index, (sheet_name, frame) in enumerate(sheets.items(), start=1):
        raw_rows: list[list[Any]] = [[_clean_cell(c) for c in row] for row in frame.values.tolist()]
        # Drop fully-empty rows but remember how many there were.
        rows = [r for r in raw_rows if any(c not in (None, "") for c in r)]
        if not rows:
            continue

        # Pick the best-scoring header candidate in the first 20 rows rather
        # than the first row that merely looks textual.
        header_index = 0
        best_score = 0.0
        for i, row in enumerate(rows[:20]):
            score = _header_score(row, rows[i + 1 :])
            if score > best_score:
                best_score = score
                header_index = i
        if best_score <= 0:
            header_index = 0

        headers = [str(c) if c not in (None, "") else f"col_{j + 1}" for j, c in enumerate(rows[header_index])]
        body = rows[header_index + 1 :]

        doc.tables.append(
            ExtractedTable(
                name=str(sheet_name),
                page=page_index,
                headers=headers,
                rows=body,
                row_count=len(body),
                column_count=len(headers),
                source="excel_sheet",
            )
        )

        # Preamble rows above the header often hold supplier/quotation info.
        preamble = rows[:header_index]
        lines = [f"=== Sheet: {sheet_name} ==="]
        for row in preamble:
            cells = [str(c) for c in row if c not in (None, "")]
            if cells:
                lines.append(" ".join(cells))
        lines.append(" | ".join(headers))
        for row in body:
            lines.append(" | ".join("" if c is None else str(c) for c in row))
        block = "\n".join(lines)
        text_blocks.append(block)
        doc.pages.append(
            PageText(page=page_index, text=block, char_count=len(block), method="native")
        )

    doc.raw_text = "\n\n".join(text_blocks)
    doc.detected_language = detect_language(doc.raw_text)
    doc.metadata["table_count"] = len(doc.tables)
    doc.metadata["source_filename"] = filename
    return doc


def extract_csv(
    data: bytes, filename: str = "", source_type: SourceType = SourceType.MANUAL_UPLOAD
) -> ProcessedDocument:
    import pandas as pd

    doc = ProcessedDocument(source_type=source_type, document_type=DocumentType.CSV)
    text = ""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if not text:
        doc.extraction_errors.append("Unable to decode CSV with utf-8 or latin-1")
        return doc

    sep = "\t" if filename.lower().endswith(".tsv") else None
    try:
        frame = pd.read_csv(io.StringIO(text), header=None, dtype=object, sep=sep, engine="python")
    except Exception as exc:
        doc.extraction_errors.append(f"Failed to parse CSV: {exc}")
        doc.raw_text = text
        return doc

    rows = [[_clean_cell(c) for c in row] for row in frame.values.tolist()]
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if rows:
        headers = [str(c) if c not in (None, "") else f"col_{i + 1}" for i, c in enumerate(rows[0])]
        body = rows[1:]
        doc.tables.append(
            ExtractedTable(
                name=filename or "csv",
                page=1,
                headers=headers,
                rows=body,
                row_count=len(body),
                column_count=len(headers),
                source="csv",
            )
        )
    doc.raw_text = text
    doc.pages.append(PageText(page=1, text=text, char_count=len(text), method="native"))
    doc.detected_language = detect_language(text)
    return doc
