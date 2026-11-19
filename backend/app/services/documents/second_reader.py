"""Second reader: look at the page image itself and compare it with what the OCR text produced.

OCR mangles digits and a model reading mangled text may "repair" them with a plausible number. A model that
looks at the picture makes different mistakes, so where the two readings disagree on an amount, a person is
asked to check the original. Nothing is changed automatically: both readings are kept.
"""
from __future__ import annotations

import logging
import re
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
    response = await provider.read_image(prompt, images, system=EXTRACTION_SYSTEM)
    if not response.ok:
        logger.info("Second reader unavailable: %s", response.error)
        return None
    data, _ = parse_json_response(response.text)
    if data is None:
        return None
    try:
        return AIExtractionResult.model_validate(_salvage(data))
    except Exception:
        return None


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


async def second_reading_issues(data: bytes, text_reading: AIExtractionResult) -> tuple[list[ValidationIssue], Optional[dict]]:
    """(issues, the image reading as a dict for storage). Both empty/None when the second reader is off or unavailable."""
    if not settings.VISION_SECOND_READER:
        return [], None
    images = page_images(data)
    other = await second_read(images) if images else None
    if other is None:
        return [], None
    return compare_readings(text_reading, other), other.model_dump(mode="json", exclude={"raw_response"})
