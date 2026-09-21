from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import Field

from app.schemas.common import APIModel, PyObjectId


class CriterionScore(APIModel):
    """One deterministic criterion score for one supplier.

    `raw_value` is the measured quantity, `score` is the 0..1 normalized score,
    `weight` comes from configuration, never from the AI.
    """

    criterion: str
    score: float = 0.0
    weight: float = 0.0
    weighted_score: float = 0.0
    raw_value: Optional[float] = None
    unit: Optional[str] = None
    data_available: bool = True
    deductions: List[str] = Field(default_factory=list)


class SupplierScore(APIModel):
    quotation_id: PyObjectId
    supplier_id: Optional[PyObjectId] = None
    supplier_name: str = "Unknown supplier"

    rank: int = 0
    overall_score: float = 0.0
    criteria: List[CriterionScore] = Field(default_factory=list)

    total_cost: Optional[float] = None
    landed_cost: Optional[float] = None
    transport_cost: Optional[float] = None
    currency: str = "INR"
    delivery_days: Optional[int] = None
    payment_days: Optional[int] = None
    reliability_score: Optional[float] = None

    coverage: float = 0.0            # fraction of requested items quoted
    matched_items: int = 0
    requested_items: int = 0

    missing_data: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    price_anomaly: Optional[str] = None  # NORMAL | POSSIBLE_ANOMALY | HIGH_ANOMALY
    data_completeness: float = 1.0


class AIExplanation(APIModel):
    """Narrative only. Generated AFTER scoring, from the scores themselves."""

    available: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    summary: Optional[str] = None
    reasoning: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    unavailable_reason: Optional[str] = None
    generated_at: Optional[str] = None
    # When a council wrote it: every member's answer, review and the monitor's decision.
    deliberation: List[dict[str, Any]] = Field(default_factory=list)


class ComparisonResult(APIModel):
    id: Optional[PyObjectId] = None
    organization_id: Optional[PyObjectId] = None
    procurement_request_id: PyObjectId
    procurement_request_title: Optional[str] = None
    currency: str = "INR"

    weights: dict[str, float] = Field(default_factory=dict)
    suppliers: List[SupplierScore] = Field(default_factory=list)
    recommended_quotation_id: Optional[PyObjectId] = None
    recommended_supplier_name: Optional[str] = None

    ai_explanation: AIExplanation = Field(default_factory=AIExplanation)
    warnings: List[str] = Field(default_factory=list)
    excluded: List[dict[str, Any]] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.now)
    method: str = "deterministic_weighted_scoring"


class ComparisonRequest(APIModel):
    """Optional per-run weight overrides. Defaults come from settings."""

    weights: Optional[dict[str, float]] = None
    include_ai_explanation: bool = True
    quotation_ids: Optional[List[str]] = None
