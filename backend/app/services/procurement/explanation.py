"""AI explanation of an already-computed ranking.

Order is strict: deterministic scoring runs first, produces the ranking, and
only then does the model get asked to describe it. The payload sent to the
model contains the finished numbers, and the response is discarded if it tries
to contradict them.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import get_ai_provider
from app.integrations.ai.prompts import EXPLANATION_SYSTEM, build_explanation_prompt
from app.schemas.comparison import AIExplanation, ComparisonResult

logger = logging.getLogger(__name__)

# Buyer-facing names for the internal criterion keys.
CRITERION_LABELS = {
    "price": "Price",
    "delivery": "Delivery",
    "payment": "Payment terms",
    "reliability": "Reliability",
    "other": "Quotation completeness",
}


def _payload(comparison: ComparisonResult) -> dict:
    """The finished, immutable facts handed to the model."""
    return {
        "procurement_request": comparison.procurement_request_title,
        "currency": comparison.currency,
        "scoring_weights": comparison.weights,
        "ranking": [
            {
                "rank": s.rank,
                "supplier": s.supplier_name,
                "overall_score": s.overall_score,
                "landed_cost": s.landed_cost,
                "delivery_days": s.delivery_days,
                "payment_days": s.payment_days,
                "reliability_score": s.reliability_score,
                "items_quoted": f"{s.matched_items} of {s.requested_items}",
                "criterion_scores": {
                    c.criterion: {
                        "score": c.score,
                        "weighted": c.weighted_score,
                        "value": c.raw_value,
                        "data_available": c.data_available,
                        "deductions": c.deductions,
                    }
                    for c in s.criteria
                },
                "missing_data": s.missing_data,
                "warnings": s.warnings,
                "price_anomaly": s.price_anomaly,
            }
            for s in comparison.suppliers
        ],
        "comparison_warnings": comparison.warnings,
        "excluded_quotations": comparison.excluded,
    }


def _deterministic_explanation(comparison: ComparisonResult) -> AIExplanation:
    """A factual, non-AI summary used when no provider is available.

    It restates computed values only. It is clearly marked as not AI-generated
    so the UI can keep the distinction the spec asks for.
    """
    if not comparison.suppliers:
        return AIExplanation(
            available=False,
            unavailable_reason="No suppliers were scored, so there is nothing to explain.",
        )

    top = comparison.suppliers[0]
    reasoning: list[str] = []
    for criterion in sorted(top.criteria, key=lambda c: c.weighted_score, reverse=True):
        value = "not stated" if criterion.raw_value is None else f"{criterion.raw_value:,.2f}"
        label = CRITERION_LABELS.get(criterion.criterion, criterion.criterion.title())
        reasoning.append(
            f"{label}: score {criterion.score:.2f} "
            f"(weight {criterion.weight:.0%}, value {value})."
        )

    risks = list(top.warnings) + list(comparison.warnings)
    if top.missing_data:
        risks.append(f"Missing data for: {', '.join(top.missing_data)}.")

    cost = f"{top.landed_cost:,.2f} {comparison.currency}" if top.landed_cost is not None else "an unstated total"
    summary = (
        f"{top.supplier_name} ranks first with a weighted score of {top.overall_score:.3f} "
        f"at {cost}. Ranking is calculated deterministically from the configured weights; "
        f"this summary restates those numbers and is not AI-generated."
    )
    return AIExplanation(
        available=True,
        provider="deterministic",
        model="rule_based_summary",
        summary=summary,
        reasoning=reasoning,
        risks=risks,
        unavailable_reason=None,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


async def explain_comparison(
    comparison: ComparisonResult, provider: Optional[AIProvider] = None
) -> AIExplanation:
    provider = provider or get_ai_provider()

    if not comparison.suppliers:
        return AIExplanation(
            available=False,
            unavailable_reason="No suppliers were scored, so there is nothing to explain.",
        )

    if not provider.is_configured():
        explanation = _deterministic_explanation(comparison)
        explanation.unavailable_reason = provider.configuration_error()
        return explanation

    response = await provider.generate(
        build_explanation_prompt(_payload(comparison)),
        system=EXPLANATION_SYSTEM,
        json_mode=True,
        temperature=0.2,
        max_output_tokens=2048,
    )
    if not response.ok:
        logger.warning("AI explanation failed: %s", response.error)
        explanation = _deterministic_explanation(comparison)
        explanation.unavailable_reason = f"AI explanation unavailable: {response.error}"
        return explanation

    try:
        text = response.text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.lstrip().lower().startswith("json"):
                text = text.lstrip()[4:]
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("AI explanation returned unparseable output: %s", exc)
        explanation = _deterministic_explanation(comparison)
        explanation.unavailable_reason = "AI explanation could not be parsed; showing computed summary."
        return explanation

    if not isinstance(data, dict):
        explanation = _deterministic_explanation(comparison)
        explanation.unavailable_reason = "AI explanation had an unexpected shape."
        return explanation

    def _list(key: str) -> list[str]:
        value = data.get(key)
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()][:8]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return AIExplanation(
        available=True,
        provider=response.provider,
        model=response.model,
        summary=str(data.get("summary") or "").strip()[:2000] or None,
        reasoning=_list("reasoning"),
        risks=_list("risks"),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
