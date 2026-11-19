"""Grounding check: every figure the model reports must be written in the document it read.

A model that sees garbled OCR text will happily fill the gap with a plausible number. This check catches
that without a second model: each money value, quantity and identifier is looked up in the source text, and
anything that is not there is flagged. Totals that are simply quantity x price are allowed, because
arithmetic is not invention.
"""
from __future__ import annotations

import re
from typing import Optional

from app.schemas.common import Severity
from app.schemas.extraction import AIExtractionResult, ValidationIssue

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
# A run this long is probably two numbers glued together by OCR ("100 292" -> "100292"), so a part of it
# is accepted as read from the document.
_GLUED_MIN_DIGITS = 5


def _tokens(text: str) -> tuple[set[float], list[str]]:
    values: set[float] = set()
    digit_runs: list[str] = []
    for raw in _NUMBER.findall(text or ""):
        cleaned = raw.replace(",", "").rstrip(".")
        try:
            values.add(round(float(cleaned), 2))
        except ValueError:
            continue
        digits = cleaned.replace(".", "")
        if len(digits) >= _GLUED_MIN_DIGITS:
            digit_runs.append(digits)
    return values, digit_runs


class _Source:
    def __init__(self, text: str) -> None:
        self.values, self.runs = _tokens(text)
        self.lower = (text or "").lower()
        self.compact = re.sub(r"\s+", "", (text or "")).upper()

    def has_number(self, value: Optional[float]) -> bool:
        if value is None:
            return True
        if round(float(value), 2) in self.values:
            return True
        digits = f"{value:.2f}".rstrip("0").rstrip(".").replace(".", "")
        return len(digits) >= 2 and any(digits in run for run in self.runs)


def grounding_issues(extraction: AIExtractionResult, source_text: str) -> list[ValidationIssue]:
    if not (source_text or "").strip():
        return []
    src = _Source(source_text)
    issues: list[ValidationIssue] = []

    def missing(field: str, code: str, value, label: str, *, severity: Severity, item_index: Optional[int] = None) -> None:
        issues.append(ValidationIssue(
            field=field, code=code, severity=severity, observed=value, item_index=item_index,
            message=f"{label} {value:,} does not appear in the document. Use only numbers written in the "
                    f"document, or leave it empty." if isinstance(value, (int, float)) else
                    f"{label} \"{value}\" does not appear in the document.",
        ))

    for index, item in enumerate(extraction.items):
        derived = (
            item.quantity * item.unit_price
            if item.quantity is not None and item.unit_price is not None else None
        )
        for name, value, label in (("quantity", item.quantity, "Quantity"), ("unit_price", item.unit_price, "Unit price")):
            if not src.has_number(value):
                missing(f"items.{index}.{name}", f"ungrounded_{name}", value, label,
                        severity=Severity.ERROR if name == "unit_price" else Severity.WARNING, item_index=index)
        total = item.total_price
        if total is not None and not src.has_number(total):
            if derived is None or abs(derived - total) > max(1.0, 0.005 * abs(total)):
                missing(f"items.{index}.total_price", "ungrounded_total_price", total, "Line total",
                        severity=Severity.ERROR, item_index=index)

    c = extraction.commercials
    for name, value, label in (
        ("subtotal", c.subtotal, "Subtotal"),
        ("tax_amount", c.tax_amount, "Tax amount"),
        ("total_amount", c.total_amount, "Total"),
        ("transportation_cost", c.transportation_cost, "Transport cost"),
    ):
        if value is not None and not src.has_number(value):
            # A subtotal or total the model worked out from the lines is arithmetic, not invention.
            line_sum = sum(
                (i.total_price if i.total_price is not None else (i.quantity or 0) * (i.unit_price or 0))
                for i in extraction.items
            )
            tax = c.tax_amount if c.tax_amount is not None else line_sum * (c.tax_percentage or 0) / 100
            reachable = {"subtotal": [line_sum],
                         "total_amount": [line_sum, line_sum + tax, line_sum + tax + (c.transportation_cost or 0),
                                          line_sum + (c.transportation_cost or 0)]}.get(name, [])
            if line_sum and any(abs(r - value) <= max(1.0, 0.005 * abs(value)) for r in reachable):
                continue
            missing(f"commercials.{name}", f"ungrounded_{name}", value, label, severity=Severity.ERROR)

    gst = extraction.supplier.gst_number
    if gst and gst.replace(" ", "").upper() not in src.compact:
        missing("supplier.gst_number", "ungrounded_gst", gst, "GST number", severity=Severity.WARNING)
    email = extraction.supplier.email
    if email and email.strip().lower() not in src.lower:
        missing("supplier.email", "ungrounded_email", email, "Supplier email", severity=Severity.WARNING)
    name = extraction.supplier.name
    if name:
        words = [w for w in re.findall(r"[a-z]{3,}", name.lower())]
        if words and sum(w in src.lower for w in words) / len(words) < 0.5:
            missing("supplier.name", "ungrounded_supplier_name", name, "Supplier name", severity=Severity.WARNING)
    return issues
