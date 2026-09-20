"""Pydantic models describing the AI structured extraction output.

Every field is optional on purpose. The extraction prompt instructs the model
to return null rather than guessing, and these models are what actually
enforce that contract: anything the model returns that does not fit is
rejected or coerced to None, never silently trusted.
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import Field, field_validator

from app.schemas.common import APIModel, Severity

_NULLISH = {"", "n/a", "na", "none", "null", "-", "--", "unknown", "not specified", "nil", "tbd"}


def blank_to_none(v: Any) -> Any:
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in _NULLISH:
            return None
        return s
    return v


def coerce_number(v: Any) -> Optional[float]:
    """Tolerantly turn messy quotation values into floats, or None.

    Returns None instead of guessing when the value cannot be read.
    """
    v = blank_to_none(v)
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        cleaned = v
        for token in [",", "₹", "Rs.", "Rs", "INR", "%", "/-", "$"]:
            cleaned = cleaned.replace(token, "")
        cleaned = cleaned.strip()
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def coerce_int(v: Any) -> Optional[int]:
    n = coerce_number(v)
    return int(n) if n is not None else None


class ExtractedSupplier(APIModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    gst_number: Optional[str] = None
    address: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def _clean(cls, v):
        return blank_to_none(v)


class ExtractedQuotationMeta(APIModel):
    reference: Optional[str] = None
    date: Optional[str] = None  # kept as raw string; parsed during validation
    validity: Optional[str] = None
    currency: Optional[str] = None

    @field_validator("*", mode="before")
    @classmethod
    def _clean(cls, v):
        return blank_to_none(v)


class ExtractedItem(APIModel):
    original_name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    gst_percentage: Optional[float] = None
    total_price: Optional[float] = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("original_name", "unit", mode="before")
    @classmethod
    def _clean_str(cls, v):
        return blank_to_none(v)

    @field_validator("quantity", "unit_price", "gst_percentage", "total_price", mode="before")
    @classmethod
    def _clean_number(cls, v):
        return coerce_number(v)

    @field_validator("attributes", mode="before")
    @classmethod
    def _clean_attrs(cls, v):
        if isinstance(v, dict):
            return {str(k): val for k, val in v.items() if val is not None and val != ""}
        return {}


class ExtractedCommercials(APIModel):
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    tax_percentage: Optional[float] = None
    total_amount: Optional[float] = None
    transportation_cost: Optional[float] = None
    delivery_days: Optional[int] = None
    delivery_date: Optional[str] = None  # as written; normalized later
    delivery_terms: Optional[str] = None
    payment_terms: Optional[str] = None
    payment_days: Optional[int] = None
    warranty: Optional[str] = None

    @field_validator("delivery_terms", "payment_terms", "warranty", mode="before")
    @classmethod
    def _clean_str(cls, v):
        return blank_to_none(v)

    @field_validator(
        "subtotal",
        "tax_amount",
        "tax_percentage",
        "total_amount",
        "transportation_cost",
        mode="before",
    )
    @classmethod
    def _clean_number(cls, v):
        return coerce_number(v)

    @field_validator("delivery_days", "payment_days", mode="before")
    @classmethod
    def _clean_int(cls, v):
        return coerce_int(v)


class AIExtractionResult(APIModel):
    """The validated envelope stored under quotation.ai_extraction."""

    supplier: ExtractedSupplier = Field(default_factory=ExtractedSupplier)
    quotation: ExtractedQuotationMeta = Field(default_factory=ExtractedQuotationMeta)
    items: List[ExtractedItem] = Field(default_factory=list)
    commercials: ExtractedCommercials = Field(default_factory=ExtractedCommercials)
    additional_attributes: dict[str, Any] = Field(default_factory=dict)

    # provenance / diagnostics
    provider: Optional[str] = None
    model: Optional[str] = None
    extracted_at: Optional[str] = None
    raw_response: Optional[str] = None
    notes: List[str] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _default_items(cls, v):
        return v or []

    @field_validator("supplier", "quotation", "commercials", mode="before")
    @classmethod
    def _default_obj(cls, v):
        return v if isinstance(v, (dict, APIModel)) else {}

    @field_validator("additional_attributes", mode="before")
    @classmethod
    def _default_attrs(cls, v):
        return v if isinstance(v, dict) else {}


class ValidationIssue(APIModel):
    """A flagged inconsistency. Original extracted values are always preserved."""

    field: str
    severity: Severity = Severity.WARNING
    code: str
    message: str
    observed: Any = None
    expected: Any = None
    item_index: Optional[int] = None


class ValidationReport(APIModel):
    issues: List[ValidationIssue] = Field(default_factory=list)
    requires_review: bool = False
    checked_at: Optional[str] = None
    error_count: int = 0
    warning_count: int = 0
