"""Second reader: look at the page image itself and compare it with what the OCR text produced.

OCR mangles digits and a model reading mangled text may "repair" them with a plausible number. A model that
looks at the picture makes different mistakes, so where the two readings disagree on an amount, a person is
asked to check the original. Nothing is changed automatically: both readings are kept.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import get_ai_provider, task_models
from app.integrations.ai.prompts import EXTRACTION_SYSTEM, build_extraction_prompt
from app.schemas.common import Severity
from app.schemas.extraction import AIExtractionResult, ValidationIssue

logger = logging.getLogger(__name__)

MAX_PAGES = 3
_MIN_NAME_MATCH = 0.6


def vision_provider() -> AIProvider:
    """The 'vision' task model if one is set, otherwise the extraction chain (its first vendor reads images)."""
    return get_ai_provider("vision" if "vision" in task_models() else "extraction")


def page_images(data: bytes) -> list[bytes]:
    """Page images to show the vision model: the picture itself, or the first pages of a PDF. Empty for other files."""
    if data[1:4] == b"PNG" or data[:3] == b"\xff\xd8\xff":
        return [data]
    if data[:4] == b"%PDF":
        try:
            import fitz  # PyMuPDF

            pdf = fitz.open(stream=data, filetype="pdf")
            try:
                return [page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).tobytes("png") for page in list(pdf)[:MAX_PAGES]]
            finally:
                pdf.close()
        except Exception as exc:  # a render problem must never fail the quotation
            logger.warning("Could not render pages for the second reader: %s", exc)
    return []


def pdf_has_images(data: bytes) -> bool:
    """True when a PDF with a text layer also carries page images. An image can sit over the text and show different
    figures from the ones the text layer holds (seen in a real quotation: text 14.00 and 8,400.00, picture 19.00 and 11,400.00)."""
    if data[:4] != b"%PDF":
        return False
    try:
        import fitz  # PyMuPDF

        pdf = fitz.open(stream=data, filetype="pdf")
        try:
            return any(page.get_images(full=True) for page in list(pdf)[:MAX_PAGES])
        finally:
            pdf.close()
    except Exception:
        return False


async def second_read(images: list[bytes], *, provider: Optional[AIProvider] = None) -> Optional[AIExtractionResult]:
    """Read the quotation from its images alone. None when no vendor could."""
    from app.services.documents.ai_extraction import _salvage, parse_json_response

    provider = provider or vision_provider()
    if not images or not provider.is_configured():
        return None
    prompt = build_extraction_prompt(
        "(The quotation is attached as image(s). Read it from the image.)",
        document_type="image", language=None, ocr_used=False,
    )
    reading = None
    for _ in range(2):  # an empty reading of a page that has a table is a model hiccup; one more try usually reads it
        response = await provider.read_image(prompt, images, system=EXTRACTION_SYSTEM)
        if not response.ok:
            logger.info("Second reader unavailable: %s", response.error)
            return reading
        data, _ = parse_json_response(response.text)
        try:
            reading = AIExtractionResult.model_validate(_salvage(data)) if data is not None else reading
        except Exception:
            pass
        if reading is not None and reading.items:
            break
    return reading


def _squash(text: Optional[str]) -> str:
    # OCR drops and adds spaces ("PVCELBOW-2INCH" vs "PVC ELBOW - 2 INCH"), so names are compared without them.
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.01, 0.005 * max(abs(a), abs(b)))


def compare_readings(text_reading: AIExtractionResult, image_reading: AIExtractionResult) -> list[ValidationIssue]:
    """One warning per amount the two readers gave differently. Only compares what both readers gave."""
    issues: list[ValidationIssue] = []

    def differ(field: str, label: str, mine: Optional[float], theirs: Optional[float], item_index: Optional[int] = None):
        if mine is None or theirs is None or _same(mine, theirs):
            return
        issues.append(ValidationIssue(
            field=field, code="readers_disagree", severity=Severity.WARNING, observed=mine, expected=theirs,
            item_index=item_index,
            message=f"{label}: the text reading says {mine:,} but the image reading says {theirs:,}. "
                    "Check this value against the original.",
        ))

    free = list(range(len(image_reading.items)))
    for index, item in enumerate(text_reading.items):
        mine = _squash(item.original_name)
        best, best_score = None, 0.0
        for j in free:
            score = SequenceMatcher(None, mine, _squash(image_reading.items[j].original_name)).ratio()
            if score > best_score:
                best, best_score = j, score
        if best is None or best_score < _MIN_NAME_MATCH:
            continue
        free.remove(best)
        other = image_reading.items[best]
        name = item.original_name or f"Line {index + 1}"
        differ(f"items.{index}.quantity", f"{name}, quantity", item.quantity, other.quantity, index)
        differ(f"items.{index}.unit_price", f"{name}, unit price", item.unit_price, other.unit_price, index)
        differ(f"items.{index}.total_price", f"{name}, line total", item.total_price, other.total_price, index)

    a, b = text_reading.commercials, image_reading.commercials
    differ("commercials.subtotal", "Subtotal", a.subtotal, b.subtotal)
    differ("commercials.total_amount", "Total", a.total_amount, b.total_amount)
    return issues


def _drop_extra_digit(mine: Optional[float], theirs: Optional[float]) -> Optional[float]:
    """Amount the image reader saw when the text reader's number is the same number plus one more digit on the end.
    Handwritten amounts end in "/-" and OCR often reads that as a 1 (4800/- becomes 48001, 12154/- becomes 121541)."""
    if mine is None or theirs is None or theirs <= 0 or mine == theirs:
        return None
    return theirs if 10 * theirs <= mine < 10 * theirs + 10 and float(mine).is_integer() and float(theirs).is_integer() else None


def reconcile_readings(text_reading: AIExtractionResult, image: AIExtractionResult,
                       text_from_ocr: bool = False) -> tuple[AIExtractionResult, list[str], bool]:
    """(the reading to keep, what was changed, whether the image reading was adopted whole).

    Nothing is changed when the readers agree. Two cases are settled in the image reading's favour because the text
    reading is plainly the damaged one: it found no line items at all, or an amount has one extra trailing digit.
    Everything else the readers disagree on is left for a person (see compare_readings)."""
    if text_from_ocr and image.items:
        # Measured on 90 labelled photos, scans and PDFs: reading the page image beat reading the OCR text on 32
        # documents and lost on 2 (all fields 84.9% to 95.8%). It is kept unless its own checks look worse.
        from app.services.procurement.validation import validate_extraction

        mine, theirs = validate_extraction(text_reading), validate_extraction(image)
        if (theirs.error_count, theirs.warning_count) <= (mine.error_count, mine.warning_count):
            adopted = image.model_copy(deep=True)
            adopted.notes.append("Read from the page image, which was clearer than the scanned text.")
            return adopted, ["Read from the page image, which was clearer than the scanned text."], True
    if not text_reading.items and image.items:
        adopted = image.model_copy(deep=True)
        adopted.notes.append("The text reading found no line items; this is the reading from the page image. Check it against the original.")
        return adopted, ["Read from the page image because the text reading found no items."], True

    merged = text_reading.model_copy(deep=True)
    notes: list[str] = []
    free = list(range(len(image.items)))
    for index, item in enumerate(merged.items):
        mine = _squash(item.original_name)
        scored = [(SequenceMatcher(None, mine, _squash(image.items[j].original_name)).ratio(), j) for j in free]
        if scored and max(scored)[0] >= _MIN_NAME_MATCH:
            match = max(scored)[1]
        elif len(merged.items) == len(image.items) and index in free:
            match = index  # badly misread handwriting: same number of lines, so pair them by position
        else:
            continue
        free.remove(match)
        other = image.items[match]
        for field in ("quantity", "unit_price", "total_price"):
            fixed = _drop_extra_digit(getattr(item, field), getattr(other, field))
            if fixed is not None:
                notes.append(f"{item.original_name}: {field.replace('_', ' ')} {getattr(item, field):,.0f} corrected to {fixed:,.0f} (an extra digit on the end).")
                setattr(item, field, fixed)
    for field in ("subtotal", "tax_amount", "total_amount", "transportation_cost"):
        fixed = _drop_extra_digit(getattr(merged.commercials, field), getattr(image.commercials, field))
        if fixed is not None:
            notes.append(f"{field.replace('_', ' ').capitalize()} {getattr(merged.commercials, field):,.0f} corrected to {fixed:,.0f} (an extra digit on the end).")
            setattr(merged.commercials, field, fixed)
    merged.notes.extend(notes)
    return merged, notes, False


@dataclass
class SecondReading:
    reading: Optional[dict] = None  # the image reading, for storage
    keep: Optional[AIExtractionResult] = None  # what the quotation should now hold (may be the original)
    changed: bool = False
    adopted: bool = False
    notes: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)


async def second_reading(data: bytes, text_reading: AIExtractionResult, text_from_ocr: bool = False) -> SecondReading:
    """Read the pages as images, settle the clear-cut disagreements, and flag the rest. Empty when switched off or unavailable."""
    if not settings.VISION_SECOND_READER:
        return SecondReading()
    images = page_images(data)
    other = await second_read(images) if images else None
    if other is None:
        return SecondReading()
    keep, notes, adopted = reconcile_readings(text_reading, other, text_from_ocr)
    return SecondReading(reading=other.model_dump(mode="json", exclude={"raw_response"}), keep=keep,
                         changed=bool(notes), adopted=adopted, notes=notes,
                         issues=[] if adopted else compare_readings(keep, other))
