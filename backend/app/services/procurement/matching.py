"""Product matching: requested items <-> quotation line items.

Three layers, cheapest first:
  1. exact normalized-string equality
  2. RapidFuzz similarity
  3. AI adjudication, invoked ONLY for pairs that land in the ambiguous band

The AI layer is deliberately rate-limited by design: it never sees a pair that
layers 1-2 already resolved confidently, so most comparisons cost nothing.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Optional

from app.core.config import settings
from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import get_ai_provider
from app.integrations.ai.prompts import MATCHING_SYSTEM, build_matching_prompt
from app.schemas.common import MatchConfidenceLevel
from app.schemas.normalized import ItemMatch, MatchResult, NormalizedQuotation
from app.services.procurement.normalization import normalize_text, normalize_unit, similarity

logger = logging.getLogger(__name__)

# How many ambiguous pairs may be escalated to the AI per quotation.
MAX_AI_ADJUDICATIONS = 5


def confidence_level(score: float) -> MatchConfidenceLevel:
    if score >= settings.MATCH_AUTO_THRESHOLD:
        return MatchConfidenceLevel.HIGH
    if score >= settings.MATCH_REVIEW_THRESHOLD:
        return MatchConfidenceLevel.MEDIUM
    if score > 0:
        return MatchConfidenceLevel.LOW
    return MatchConfidenceLevel.NONE


def _units_compatible(requested_unit: Optional[str], quoted_unit: Optional[str]) -> Optional[bool]:
    if not requested_unit or not quoted_unit:
        return None  # unknown, not incompatible
    left, right = normalize_unit(requested_unit), normalize_unit(quoted_unit)
    if left is None or right is None:
        return None
    return left == right


async def match_items(
    request_items: list[dict[str, Any]],
    normalized: NormalizedQuotation,
    *,
    quotation_id: str,
    procurement_request_id: str,
    provider: Optional[AIProvider] = None,
    allow_ai: bool = True,
) -> MatchResult:
    """Match each requested item against the quotation's line items."""
    result = MatchResult(quotation_id=quotation_id, procurement_request_id=procurement_request_id)
    candidates = [
        {
            "id": item.line_id,
            "name": item.original_name or item.normalized_name or "",
            "normalized": item.normalized_name or "",
            "unit": item.unit,
            "unit_price": item.unit_price,
            "quantity": item.quantity,
        }
        for item in normalized.items
    ]

    ambiguous: list[tuple[int, dict]] = []

    for index, requested in enumerate(request_items):
        requested_name = str(requested.get("name") or "")
        match = ItemMatch(
            request_item_id=str(requested.get("item_id") or f"req-{index + 1}"),
            request_item_name=requested_name,
        )

        if not candidates:
            match.reasons.append("The quotation contains no line items to match against.")
            result.matches.append(match)
            continue

        requested_normalized = normalize_text(requested_name)

        # --- Layer 1: exact normalized equality ---
        exact = next((c for c in candidates if c["normalized"] and c["normalized"] == requested_normalized), None)
        if exact is not None:
            _apply(match, exact, score=1.0, method="exact")
            match.reasons.append("Normalized descriptions are identical.")
            match.unit_compatible = _units_compatible(requested.get("unit"), exact["unit"])
            result.matches.append(match)
            continue

        # --- Layer 2: fuzzy ---
        scored = sorted(
            ((similarity(requested_name, c["name"]), c) for c in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score, best = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else 0.0

        match.unit_compatible = _units_compatible(requested.get("unit"), best["unit"])

        if best_score >= settings.MATCH_AUTO_THRESHOLD:
            _apply(match, best, score=best_score, method="fuzzy")
            match.reasons.append(f"High fuzzy similarity ({best_score:.2f}).")
            if match.unit_compatible is False:
                # A confident text match with an incompatible unit is not safe
                # to auto-accept; downgrade rather than force it.
                match.requires_review = True
                match.confidence_level = MatchConfidenceLevel.MEDIUM
                match.reasons.append(
                    f"Units differ (requested '{requested.get('unit')}' vs quoted '{best['unit']}')."
                )
        elif best_score >= settings.MATCH_REVIEW_THRESHOLD:
            _apply(match, best, score=best_score, method="fuzzy")
            match.requires_review = True
            match.reasons.append(f"Moderate similarity ({best_score:.2f}); flagged for review.")
            # Close top-2 scores mean the text alone cannot decide.
            if allow_ai and (best_score - runner_up) < 0.15 and len(ambiguous) < MAX_AI_ADJUDICATIONS:
                ambiguous.append((len(result.matches), {"requested": requested_name, "candidates": candidates}))
        else:
            match.matched = False
            match.score = best_score
            match.confidence_level = confidence_level(best_score)
            match.requires_review = True
            match.reasons.append(
                f"No candidate exceeded the review threshold (best {best_score:.2f}); manual review required."
            )

        result.matches.append(match)

    # --- Layer 3: AI adjudication for the genuinely ambiguous only ---
    if ambiguous and allow_ai:
        provider = provider or get_ai_provider()
        if provider.is_configured():
            for match_index, payload in ambiguous:
                decision = await _adjudicate(provider, payload["requested"], payload["candidates"])
                if decision is None:
                    continue
                result.ai_assisted = True
                match = result.matches[match_index]
                match_id, ai_confidence, reason = decision
                if match_id is None:
                    match.matched = False
                    match.quotation_line_id = None
                    match.quotation_item_name = None
                    match.method = "ai"
                    match.requires_review = True
                    match.reasons.append(f"AI adjudication: no candidate is the same product. {reason}")
                else:
                    chosen = next((c for c in payload["candidates"] if c["id"] == match_id), None)
                    if chosen is not None:
                        _apply(match, chosen, score=max(match.score, ai_confidence), method="ai")
                        match.requires_review = ai_confidence < settings.MATCH_AUTO_THRESHOLD
                        match.reasons.append(f"AI adjudication (confidence {ai_confidence:.2f}): {reason}")
        else:
            for match_index, _ in ambiguous:
                result.matches[match_index].reasons.append(
                    "AI adjudication unavailable (no AI provider configured); left for manual review."
                )

    result.matched_count = sum(1 for m in result.matches if m.matched and not m.requires_review)
    result.review_count = sum(1 for m in result.matches if m.matched and m.requires_review)
    result.unmatched_count = sum(1 for m in result.matches if not m.matched)
    total = len(result.matches) or 1
    result.coverage = round((result.matched_count + result.review_count) / total, 4)
    return result


def _apply(match: ItemMatch, candidate: dict, *, score: float, method: str) -> None:
    match.quotation_line_id = candidate["id"]
    match.quotation_item_name = candidate["name"]
    match.score = round(score, 4)
    match.confidence_level = confidence_level(score)
    match.method = method
    match.matched = True
    match.requires_review = score < settings.MATCH_AUTO_THRESHOLD
    match.unit_price = candidate.get("unit_price")
    match.quantity = candidate.get("quantity")


async def _adjudicate(
    provider: AIProvider, requested: str, candidates: list[dict]
) -> Optional[tuple[Optional[str], float, str]]:
    prompt = build_matching_prompt(requested, candidates)
    response = await provider.generate(prompt, system=MATCHING_SYSTEM, json_mode=True, temperature=0.0)
    if not response.ok:
        logger.warning("AI matching failed: %s", response.error)
        return None
    try:
        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("```")[1] if "```" in text[3:] else text[3:]
            text = text.lstrip("json").strip()
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("AI matching returned unparseable output: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    match_id = data.get("match_id")
    match_id = str(match_id) if match_id not in (None, "", "null") else None
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = min(max(confidence, 0.0), 1.0)
    reason = str(data.get("reason") or "").strip()[:400]
    # Guard against a hallucinated id.
    if match_id is not None and match_id not in {c["id"] for c in candidates}:
        logger.warning("AI returned an unknown candidate id %r; discarding.", match_id)
        return None
    return match_id, confidence, reason
