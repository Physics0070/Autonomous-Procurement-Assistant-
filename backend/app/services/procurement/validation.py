"""Validation of extracted quotation data.

The rule this module exists to enforce: never silently modify AI output.
Every check either passes, or records a ValidationIssue that names the observed
value and what was expected. The extraction itself is left untouched.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from app.core.gstin import has_valid_check_digit, is_valid_gstin
from app.schemas.extraction import AIExtractionResult, ValidationIssue, ValidationReport
from app.schemas.common import Severity

# Money comparisons need a tolerance: quotations round differently at each line. Printed figures differ from the
# arithmetic by rounding only (a rupee or two), so the tolerance is tight. It was 2%, which let a supplier's ₹1,000
# mistake on a ₹1 lakh quotation through unflagged (measured on the labelled benchmark: 5 of 11 such errors missed).
ABS_TOLERANCE = 2.0
REL_TOLERANCE = 0.0001  # 0.01%: ₹10 on ₹1 lakh
ARITHMETIC_CODES = {"line_total_mismatch", "subtotal_mismatch", "total_mismatch"}


# Discounts, applied the same way everywhere (validation, normalisation, purchase orders). A printed amount wins over a
# printed percentage; nothing is ever inferred from the difference between two totals.
def line_net_total(quantity: Optional[float], unit_price: Optional[float], discount_percentage: Optional[float] = None,
                   discount_amount: Optional[float] = None) -> Optional[float]:
    """quantity x unit price, less the line's own discount."""
    if quantity is None or unit_price is None:
        return None
    gross = quantity * unit_price
    if discount_amount is not None:
        return gross - discount_amount
    if discount_percentage is not None:
        return gross * (1 - discount_percentage / 100.0)
    return gross


def quotation_discount(base: Optional[float], discount_amount: Optional[float],
                       discount_percentage: Optional[float]) -> float:
    """The quotation-level discount taken off the subtotal before tax (0 when none is printed)."""
    if discount_amount is not None:
        return abs(discount_amount)
    if discount_percentage is not None and base is not None:
        return base * discount_percentage / 100.0
    return 0.0

MAX_PLAUSIBLE_QUANTITY = 1_000_000
MAX_PLAUSIBLE_UNIT_PRICE = 10_000_000
MAX_PLAUSIBLE_TOTAL = 1_000_000_000

_DATE_FORMATS = (
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d-%m-%y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
    "%d-%b-%Y", "%d-%b-%y", "%d %b %y", "%d/%b/%Y", "%d.%m.%y", "%d-%B-%Y",
)
_MONTH_DATE_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-./]+([A-Za-z]{3,9})[\s\-./,]+(\d{2,4})\b")


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    cleaned = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    named = _MONTH_DATE_RE.search(cleaned)  # "Dated 25th October 2026", "25-Oct-26"
    if named:
        day, month, year = named.groups()
        for fmt in ("%d %b %Y", "%d %B %Y", "%d %b %y", "%d %B %y"):
            try:
                return datetime.strptime(f"{day} {month[:3] if len(month) > 3 and fmt.endswith('%b %Y') else month} {year}", fmt)
            except ValueError:
                continue
    match = re.search(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{2,4}", cleaned)
    if match:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(match.group(0), fmt)
            except ValueError:
                continue
    return None


def _close_enough(a: float, b: float) -> bool:
    if a is None or b is None:
        return True
    diff = abs(a - b)
    return diff <= ABS_TOLERANCE or diff <= REL_TOLERANCE * max(abs(a), abs(b), 1.0)


def validate_extraction(extraction: AIExtractionResult, source_text: Optional[str] = None) -> ValidationReport:
    """``source_text`` (the text the model read) turns on the grounding check: figures the document does not contain are flagged."""
    issues: list[ValidationIssue] = []

    def add(
        field: str,
        code: str,
        message: str,
        *,
        severity: Severity = Severity.WARNING,
        observed=None,
        expected=None,
        item_index: Optional[int] = None,
    ) -> None:
        issues.append(
            ValidationIssue(
                field=field,
                code=code,
                message=message,
                severity=severity,
                observed=observed,
                expected=expected,
                item_index=item_index,
            )
        )

    # ------------------------------------------------------------------
    # Supplier identity
    # ------------------------------------------------------------------
    supplier = extraction.supplier
    if not supplier.name:
        add("supplier.name", "missing_supplier_name", "No supplier name could be identified.")
    if supplier.gst_number and not is_valid_gstin(supplier.gst_number):
        add(
            "supplier.gst_number",
            "invalid_gst_format",
            "GST number does not match the 15-character GSTIN format.",
            observed=supplier.gst_number,
        )
    elif supplier.gst_number and not has_valid_check_digit(supplier.gst_number):
        add(
            "supplier.gst_number",
            "gst_check_digit_failed",
            "GST number looks right but fails its check digit, so a character may have been misread.",
            observed=supplier.gst_number,
        )
    if supplier.email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", supplier.email.strip()):
        add("supplier.email", "invalid_email", "Supplier email is not a valid address.", observed=supplier.email)

    # ------------------------------------------------------------------
    # Quotation metadata
    # ------------------------------------------------------------------
    if extraction.quotation.date:
        parsed = parse_date(extraction.quotation.date)
        if parsed is None:
            add(
                "quotation.date",
                "unparseable_date",
                "Quotation date could not be parsed into a calendar date.",
                observed=extraction.quotation.date,
            )
        else:
            now = datetime.now()
            if parsed > now:
                add(
                    "quotation.date",
                    "future_date",
                    "Quotation date is in the future.",
                    observed=extraction.quotation.date,
                )
            elif (now - parsed).days > 365 * 3:
                add(
                    "quotation.date",
                    "very_old_date",
                    "Quotation date is more than three years old.",
                    observed=extraction.quotation.date,
                )

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------
    if not extraction.items:
        add(
            "items",
            "no_items",
            "No line items were extracted from this quotation.",
            severity=Severity.ERROR,
        )

    computed_subtotal = 0.0
    subtotal_is_complete = bool(extraction.items)

    for index, item in enumerate(extraction.items):
        prefix = f"items.{index}"
        if not item.original_name:
            add(f"{prefix}.original_name", "missing_item_name", "Line item has no description.",
                severity=Severity.ERROR, item_index=index)

        if item.quantity is not None:
            if item.quantity <= 0:
                add(f"{prefix}.quantity", "non_positive_quantity",
                    "Quantity is zero or negative.", severity=Severity.ERROR,
                    observed=item.quantity, item_index=index)
            elif item.quantity > MAX_PLAUSIBLE_QUANTITY:
                add(f"{prefix}.quantity", "implausible_quantity",
                    "Quantity is implausibly large.", observed=item.quantity, item_index=index)

        if item.unit_price is not None:
            if item.unit_price < 0:
                add(f"{prefix}.unit_price", "negative_price", "Unit price is negative.",
                    severity=Severity.ERROR, observed=item.unit_price, item_index=index)
            elif item.unit_price > MAX_PLAUSIBLE_UNIT_PRICE:
                add(f"{prefix}.unit_price", "implausible_price",
                    "Unit price is implausibly large.", observed=item.unit_price, item_index=index)

        if item.gst_percentage is not None and not (0 <= item.gst_percentage <= 40):
            add(f"{prefix}.gst_percentage", "implausible_tax_rate",
                "Tax percentage is outside the plausible 0-40% range.",
                observed=item.gst_percentage, item_index=index)

        if item.total_price is not None and item.total_price < 0:
            add(f"{prefix}.total_price", "negative_total", "Line total is negative.",
                severity=Severity.ERROR, observed=item.total_price, item_index=index)

        # Cross-check quantity x unit price against the stated line total.
        if item.quantity is not None and item.unit_price is not None:
            expected = line_net_total(item.quantity, item.unit_price, item.discount_percentage, item.discount_amount)
            if item.total_price is not None and not _close_enough(expected, item.total_price):
                less = " less the line discount" if item.discount_percentage is not None or item.discount_amount is not None else ""
                add(
                    f"{prefix}.total_price",
                    "line_total_mismatch",
                    f"Line total does not equal quantity x unit price{less} "
                    f"({item.quantity} x {item.unit_price}{less} = {expected:,.2f}).",
                    observed=item.total_price,
                    expected=round(expected, 2),
                    item_index=index,
                )
            computed_subtotal += expected
        elif item.total_price is not None:
            computed_subtotal += item.total_price
        else:
            subtotal_is_complete = False

        missing = [
            name
            for name, value in (
                ("quantity", item.quantity),
                ("unit_price", item.unit_price),
                ("total_price", item.total_price),
            )
            if value is None
        ]
        if missing:
            # A priced line with neither quantity nor rate is usually OCR gluing two numbers together
            # ("100 292" read as "100292"). That is an error, so the extraction agent re-reads once
            # with the hint that quantity x unit price must equal the line total.
            glued = item.total_price is not None and item.quantity is None and item.unit_price is None
            add(
                f"{prefix}",
                "incomplete_item",
                f"Line item is missing {', '.join(missing)}."
                + (" Digits may have been merged by OCR: quantity x unit price must equal the line total, "
                   "so split the digits accordingly." if glued else ""),
                severity=Severity.ERROR if glued else Severity.WARNING,
                observed=item.original_name,
                item_index=index,
            )

    # ------------------------------------------------------------------
    # Commercial totals
    # ------------------------------------------------------------------
    commercials = extraction.commercials
    if commercials.subtotal is not None and subtotal_is_complete and computed_subtotal > 0:
        if not _close_enough(computed_subtotal, commercials.subtotal):
            add(
                "commercials.subtotal",
                "subtotal_mismatch",
                f"Stated subtotal does not match the sum of line items ({computed_subtotal:,.2f}).",
                observed=commercials.subtotal,
                expected=round(computed_subtotal, 2),
            )

    if commercials.tax_percentage is not None and not (0 <= commercials.tax_percentage <= 40):
        add("commercials.tax_percentage", "implausible_tax_rate",
            "Tax percentage is outside the plausible 0-40% range.",
            observed=commercials.tax_percentage)

    # subtotal + tax + freight should reconcile with the stated total.
    base = commercials.subtotal
    if base is not None and commercials.total_amount is not None:
        discount = quotation_discount(base, commercials.discount_amount, commercials.discount_percentage)
        tax = commercials.tax_amount
        if tax is None and commercials.tax_percentage is not None:
            tax = (base - discount) * commercials.tax_percentage / 100.0
        freight = commercials.transportation_cost or 0.0
        # Freight that is also a line ("TRANSPORTATION 600") is already inside the subtotal.
        if freight and any(
            i.total_price is not None and abs(i.total_price - freight) <= ABS_TOLERANCE
            and re.search(r"transport|freight|carriage|cartage|delivery|tempo|loading", i.original_name or "", re.I)
            for i in extraction.items
        ):
            freight = 0.0
        if tax is not None:
            # Some quotations print the subtotal before the discount, some after it ("taxable value"); both are accepted.
            nets = [base - discount, base] if discount else [base]
            expected_total = nets[0] + tax + freight
            # Prices that include GST, and "GST extra" quotations that never add it, print a total equal to the subtotal.
            reconciles = any(_close_enough(net + extra, commercials.total_amount) for net in nets for extra in (tax + freight, freight))
            if not reconciles:
                less = f" - {discount:,.2f}" if discount else ""
                add(
                    "commercials.total_amount",
                    "total_mismatch",
                    f"Total does not reconcile with subtotal{' - discount' if discount else ''} + tax + transportation "
                    f"({base:,.2f}{less} + {tax:,.2f} + {freight:,.2f} = {expected_total:,.2f}).",
                    observed=commercials.total_amount,
                    expected=round(expected_total, 2),
                )

    if commercials.total_amount is not None:
        if commercials.total_amount <= 0:
            add("commercials.total_amount", "non_positive_total",
                "Total amount is zero or negative.", severity=Severity.ERROR,
                observed=commercials.total_amount)
        elif commercials.total_amount > MAX_PLAUSIBLE_TOTAL:
            add("commercials.total_amount", "implausible_total",
                "Total amount is implausibly large.", observed=commercials.total_amount)
    else:
        add("commercials.total_amount", "missing_total", "No total amount was found.")

    if commercials.delivery_days is not None and not (0 <= commercials.delivery_days <= 365):
        add("commercials.delivery_days", "implausible_delivery",
            "Delivery lead time is outside the plausible 0-365 day range.",
            observed=commercials.delivery_days)

    if commercials.payment_days is not None and not (0 <= commercials.payment_days <= 365):
        add("commercials.payment_days", "implausible_payment_terms",
            "Payment period is outside the plausible 0-365 day range.",
            observed=commercials.payment_days)

    if source_text:
        from app.services.procurement.grounding import grounding_issues

        issues.extend(grounding_issues(extraction, source_text))

    errors = sum(1 for i in issues if i.severity == Severity.ERROR)
    warnings = sum(1 for i in issues if i.severity == Severity.WARNING)
    return ValidationReport(
        issues=issues,
        # Any hard error, or a meaningful pile of warnings, needs a human.
        # A total that does not add up must be looked at before it can reach a purchase order.
        requires_review=errors > 0 or warnings >= 3
        or any(i.code == "incomplete_item" or i.code in ARITHMETIC_CODES for i in issues),
        checked_at=datetime.now(timezone.utc).isoformat(),
        error_count=errors,
        warning_count=warnings,
    )
