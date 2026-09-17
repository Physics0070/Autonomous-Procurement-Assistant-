"""Builds canonical NormalizedQuotation from a validated AIExtractionResult.

This is the boundary where source-shaped data becomes engine-shaped data.
Everything downstream (matching, comparison, analytics) reads only this.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from app.schemas.extraction import AIExtractionResult
from app.schemas.normalized import (
    NormalizationTrace,
    NormalizedDelivery,
    NormalizedItem,
    NormalizedPaymentTerms,
    NormalizedPricing,
    NormalizedQuotation,
    NormalizedSupplier,
)
from app.services.procurement.normalization import (
    convert_quantity,
    normalize_text,
    normalize_tokens,
    normalize_unit,
)
from app.services.procurement.validation import parse_date

_VALIDITY_DAYS_RE = re.compile(r"(\d{1,3})\s*(?:days?|दिन)", re.IGNORECASE)
_ADVANCE_RE = re.compile(r"(\d{1,3})\s*%\s*(?:advance|adv)", re.IGNORECASE)
_INCOTERM_RE = re.compile(
    r"\b(ex[\s-]?works|ex[\s-]?godown|fob|cif|cfr|dap|ddp|exw|free\s+delivery|door\s+delivery)\b",
    re.IGNORECASE,
)


def _validity_days(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = _VALIDITY_DAYS_RE.search(value)
    return int(match.group(1)) if match else None


def normalize_quotation(extraction: AIExtractionResult, currency_default: str = "INR") -> NormalizedQuotation:
    normalized = NormalizedQuotation()
    missing: list[str] = []

    # ------------------------------------------------------------------
    # Supplier
    # ------------------------------------------------------------------
    supplier = extraction.supplier
    normalized.supplier = NormalizedSupplier(
        name=supplier.name,
        normalized_name=normalize_text(supplier.name) or None,
        email=supplier.email.lower().strip() if supplier.email else None,
        phone=re.sub(r"[^\d+]", "", supplier.phone) if supplier.phone else None,
        gst_number=supplier.gst_number.upper().strip() if supplier.gst_number else None,
        address=supplier.address,
    )
    if not supplier.name:
        missing.append("supplier.name")

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    computed_subtotal = 0.0
    subtotal_complete = bool(extraction.items)

    for index, item in enumerate(extraction.items):
        canonical_unit = normalize_unit(item.unit)
        base_quantity, base_unit = convert_quantity(item.quantity, item.unit)
        computed_total = (
            round(item.quantity * item.unit_price, 4)
            if item.quantity is not None and item.unit_price is not None
            else None
        )

        line_total = item.total_price if item.total_price is not None else computed_total
        if line_total is not None:
            computed_subtotal += line_total
        else:
            subtotal_complete = False

        normalized.items.append(
            NormalizedItem(
                line_id=f"line-{index + 1}",
                original_name=item.original_name,
                normalized_name=normalize_text(item.original_name) or None,
                normalized_tokens=normalize_tokens(item.original_name),
                quantity=item.quantity,
                unit=item.unit,
                normalized_unit=canonical_unit or base_unit,
                normalized_quantity=base_quantity,
                unit_price=item.unit_price,
                tax_percentage=item.gst_percentage,
                total_price=item.total_price,
                computed_total=computed_total,
                attributes=dict(item.attributes),
                trace=NormalizationTrace(
                    original_value=item.original_name,
                    normalized_value=normalize_text(item.original_name) or None,
                    method="deterministic",
                    confidence=1.0 if item.original_name else 0.0,
                    notes=(
                        []
                        if canonical_unit or not item.unit
                        else [f"Unit '{item.unit}' is not a recognised unit of measure."]
                    ),
                ),
            )
        )

    if not extraction.items:
        missing.append("items")

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------
    commercials = extraction.commercials
    currency = (extraction.quotation.currency or currency_default).upper()
    tax_amount = commercials.tax_amount
    if tax_amount is None and commercials.tax_percentage is not None and commercials.subtotal is not None:
        # Derived, and marked as such - the stored extraction keeps its null.
        tax_amount = round(commercials.subtotal * commercials.tax_percentage / 100.0, 2)

    subtotal = commercials.subtotal
    if subtotal is None and subtotal_complete and computed_subtotal > 0:
        subtotal = round(computed_subtotal, 2)

    landed_total = commercials.total_amount
    if landed_total is None and subtotal is not None:
        landed_total = round(subtotal + (tax_amount or 0.0) + (commercials.transportation_cost or 0.0), 2)

    normalized.pricing = NormalizedPricing(
        currency=currency,
        subtotal=commercials.subtotal,
        tax_amount=commercials.tax_amount,
        tax_percentage=commercials.tax_percentage,
        transportation_cost=commercials.transportation_cost,
        total_amount=commercials.total_amount,
        computed_subtotal=round(computed_subtotal, 2) if subtotal_complete and computed_subtotal else None,
        landed_total=landed_total,
    )
    for field, value in (
        ("pricing.subtotal", commercials.subtotal),
        ("pricing.total_amount", commercials.total_amount),
        ("pricing.tax", commercials.tax_amount if commercials.tax_amount is not None else commercials.tax_percentage),
    ):
        if value is None:
            missing.append(field)

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------
    incoterm = None
    if commercials.delivery_terms:
        match = _INCOTERM_RE.search(commercials.delivery_terms)
        incoterm = match.group(1).lower() if match else None
    normalized.delivery = NormalizedDelivery(
        delivery_days=commercials.delivery_days,
        delivery_terms=commercials.delivery_terms,
        incoterm=incoterm,
    )
    if commercials.delivery_days is None:
        missing.append("delivery.delivery_days")

    # ------------------------------------------------------------------
    # Payment terms
    # ------------------------------------------------------------------
    advance = None
    if commercials.payment_terms:
        match = _ADVANCE_RE.search(commercials.payment_terms)
        advance = float(match.group(1)) if match else None
    normalized.payment_terms = NormalizedPaymentTerms(
        payment_days=commercials.payment_days,
        advance_percentage=advance,
        raw_terms=commercials.payment_terms,
    )
    if commercials.payment_days is None and advance is None:
        missing.append("payment_terms.payment_days")

    # ------------------------------------------------------------------
    # Quotation metadata
    # ------------------------------------------------------------------
    normalized.quotation_reference = extraction.quotation.reference
    parsed_date = parse_date(extraction.quotation.date)
    normalized.quotation_date = parsed_date.date().isoformat() if parsed_date else extraction.quotation.date
    normalized.validity_days = _validity_days(extraction.quotation.validity)
    normalized.warranty = commercials.warranty
    normalized.additional_attributes = {
        k: v for k, v in extraction.additional_attributes.items() if not k.startswith("_")
    }
    normalized.missing_fields = missing
    normalized.normalized_at = datetime.now(timezone.utc).isoformat()
    return normalized
