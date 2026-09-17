"""Canonical normalized procurement data.

This structure is deliberately independent of the source format AND of
MongoDB. It is what the comparison engine, matching engine and analytics
consume. Swapping the persistence layer must not require changing this.
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import Field

from app.schemas.common import APIModel, MatchConfidenceLevel


class NormalizedSupplier(APIModel):
    name: Optional[str] = None
    normalized_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gst_number: Optional[str] = None
    address: Optional[str] = None
    supplier_id: Optional[str] = None  # link to the suppliers collection


class NormalizationTrace(APIModel):
    """How a value got from original -> normalized. Never discards the original."""

    original_value: Optional[str] = None
    normalized_value: Optional[str] = None
    method: str = "deterministic"  # deterministic | fuzzy | ai | manual
    confidence: float = 1.0
    notes: List[str] = Field(default_factory=list)


class NormalizedItem(APIModel):
    line_id: str
    original_name: Optional[str] = None
    normalized_name: Optional[str] = None
    normalized_tokens: List[str] = Field(default_factory=list)

    quantity: Optional[float] = None
    unit: Optional[str] = None                 # original unit as written
    normalized_unit: Optional[str] = None      # canonical unit symbol
    normalized_quantity: Optional[float] = None  # quantity in the canonical unit

    unit_price: Optional[float] = None
    tax_percentage: Optional[float] = None
    total_price: Optional[float] = None
    computed_total: Optional[float] = None     # qty * unit_price, for cross-checking

    attributes: dict[str, Any] = Field(default_factory=dict)
    trace: NormalizationTrace = Field(default_factory=NormalizationTrace)


class NormalizedPricing(APIModel):
    currency: str = "INR"
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    tax_percentage: Optional[float] = None
    transportation_cost: Optional[float] = None
    total_amount: Optional[float] = None
    computed_subtotal: Optional[float] = None
    landed_total: Optional[float] = None  # best available all-in figure


class NormalizedDelivery(APIModel):
    delivery_days: Optional[int] = None
    delivery_terms: Optional[str] = None
    incoterm: Optional[str] = None


class NormalizedPaymentTerms(APIModel):
    payment_days: Optional[int] = None
    advance_percentage: Optional[float] = None
    raw_terms: Optional[str] = None


class NormalizedQuotation(APIModel):
    """The canonical normalized_data block on a quotation."""

    supplier: NormalizedSupplier = Field(default_factory=NormalizedSupplier)
    items: List[NormalizedItem] = Field(default_factory=list)
    pricing: NormalizedPricing = Field(default_factory=NormalizedPricing)
    delivery: NormalizedDelivery = Field(default_factory=NormalizedDelivery)
    payment_terms: NormalizedPaymentTerms = Field(default_factory=NormalizedPaymentTerms)

    quotation_reference: Optional[str] = None
    quotation_date: Optional[str] = None
    validity_days: Optional[int] = None
    warranty: Optional[str] = None

    additional_attributes: dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    normalized_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Product matching
# ---------------------------------------------------------------------------


class ItemMatch(APIModel):
    """One requested item matched (or not) against one quotation line."""

    request_item_id: str
    request_item_name: str
    quotation_line_id: Optional[str] = None
    quotation_item_name: Optional[str] = None

    score: float = 0.0
    confidence_level: MatchConfidenceLevel = MatchConfidenceLevel.NONE
    method: str = "none"  # exact | deterministic | fuzzy | ai | manual | none
    requires_review: bool = True
    matched: bool = False

    unit_price: Optional[float] = None
    quantity: Optional[float] = None
    unit_compatible: Optional[bool] = None
    reasons: List[str] = Field(default_factory=list)


class MatchResult(APIModel):
    quotation_id: str
    procurement_request_id: str
    matches: List[ItemMatch] = Field(default_factory=list)
    matched_count: int = 0
    review_count: int = 0
    unmatched_count: int = 0
    coverage: float = 0.0  # fraction of requested items confidently matched
    ai_assisted: bool = False
