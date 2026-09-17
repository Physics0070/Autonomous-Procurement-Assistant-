"""Supplier comparison engine.

Every number here is computed deterministically in Python. The AI is never
asked to rank, score, or weigh anything - it only receives the finished result
to describe in prose (see explanation.py).

Scoring is relative: each criterion is normalized across the suppliers being
compared, so a score answers "how does this quote compare with the others on
the table", which is the question a buyer is actually asking.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from app.core.config import settings
from app.schemas.comparison import ComparisonResult, CriterionScore, SupplierScore
from app.services.procurement.anomaly import AnomalyStatus, worst_status

logger = logging.getLogger(__name__)

# Penalty applied to a criterion when the underlying data is missing. Not zero:
# a missing value should hurt, but not eliminate an otherwise strong supplier.
MISSING_DATA_SCORE = 0.35


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(w, 0.0) for w in weights.values())
    if total <= 0:
        # Fall back to equal weighting rather than dividing by zero.
        return {k: 1.0 / len(weights) for k in weights}
    return {k: max(w, 0.0) / total for k, w in weights.items()}


def _lower_is_better(value: Optional[float], values: list[float]) -> float:
    """Normalize so the smallest value scores 1.0 and the largest 0.0."""
    if value is None or not values:
        return MISSING_DATA_SCORE
    low, high = min(values), max(values)
    if high == low:
        return 1.0
    return round(1.0 - (value - low) / (high - low), 4)


def _higher_is_better(value: Optional[float], values: list[float]) -> float:
    if value is None or not values:
        return MISSING_DATA_SCORE
    low, high = min(values), max(values)
    if high == low:
        return 1.0
    return round((value - low) / (high - low), 4)


def build_comparison(
    procurement_request: dict[str, Any],
    quotations: list[dict[str, Any]],
    *,
    suppliers_by_id: Optional[dict[str, dict[str, Any]]] = None,
    weight_overrides: Optional[dict[str, float]] = None,
) -> ComparisonResult:
    """Score and rank quotations for one procurement request."""
    suppliers_by_id = suppliers_by_id or {}
    weights = _normalize_weights({**settings.scoring_weights(), **(weight_overrides or {})})

    requested_items = procurement_request.get("items") or []
    requested_count = len(requested_items)
    currency = procurement_request.get("currency") or "INR"

    result = ComparisonResult(
        procurement_request_id=str(procurement_request.get("id")),
        procurement_request_title=procurement_request.get("title"),
        currency=currency,
        weights=weights,
    )

    # ------------------------------------------------------------------
    # Gather raw measurements
    # ------------------------------------------------------------------
    rows: list[dict[str, Any]] = []
    for quotation in quotations:
        status = quotation.get("processing_status")
        if status in ("FAILED", "UPLOADED", "QUEUED", "EXTRACTING", "AI_EXTRACTING", "NORMALIZING"):
            result.excluded.append(
                {
                    "quotation_id": str(quotation.get("id")),
                    "supplier_name": quotation.get("supplier_name"),
                    "reason": f"Processing is not complete (status {status}).",
                }
            )
            continue

        # Corrections take precedence over the machine-produced view.
        data = quotation.get("effective_data") or quotation.get("normalized_data") or {}
        pricing = data.get("pricing") or {}
        delivery = data.get("delivery") or {}
        payment = data.get("payment_terms") or {}
        supplier_block = data.get("supplier") or {}
        match_result = quotation.get("match_result") or {}
        validation = quotation.get("validation") or {}

        supplier_id = quotation.get("supplier_id")
        supplier_doc = suppliers_by_id.get(str(supplier_id)) if supplier_id else None
        reliability = None
        if supplier_doc:
            reliability = (supplier_doc.get("reliability") or {}).get("score")

        landed = pricing.get("landed_total")
        if landed is None:
            landed = pricing.get("total_amount")
        subtotal = pricing.get("subtotal")

        # Whether this total actually includes tax. A quotation saying "GST
        # extra as applicable" produces a tax-exclusive total that would look
        # artificially cheap next to tax-inclusive ones.
        tax_included = (
            pricing.get("tax_amount") is not None or pricing.get("tax_percentage") is not None
        )

        payment_days = payment.get("payment_days")
        if payment_days is None and payment.get("advance_percentage") is not None:
            payment_days = 0  # advance payment means no credit period

        rows.append(
            {
                "quotation": quotation,
                "supplier_id": supplier_id,
                "supplier_name": (
                    quotation.get("supplier_name")
                    or supplier_block.get("name")
                    or (supplier_doc or {}).get("name")
                    or "Unknown supplier"
                ),
                "landed": landed,
                "subtotal": subtotal,
                "tax_included": tax_included,
                "delivery_days": delivery.get("delivery_days"),
                "payment_days": payment_days,
                "reliability": reliability,
                "matched": match_result.get("matched_count", 0) + match_result.get("review_count", 0),
                "coverage": match_result.get("coverage"),
                "validation": validation,
                "items": data.get("items") or [],
                "currency": pricing.get("currency") or currency,
            }
        )

    if not rows:
        result.warnings.append("No processed quotations are available to compare for this request.")
        return result

    mixed_currencies = {r["currency"] for r in rows if r["currency"]}
    if len(mixed_currencies) > 1:
        result.warnings.append(
            f"Quotations use different currencies ({', '.join(sorted(mixed_currencies))}); "
            "totals are not directly comparable."
        )

    landed_values = [r["landed"] for r in rows if r["landed"] is not None]
    any_tax_inclusive = any(r["tax_included"] for r in rows)
    if any_tax_inclusive and not all(r["tax_included"] for r in rows):
        result.warnings.append(
            "Tax could not be identified on every quotation. Totals may not be like-for-like "
            "until you confirm which of them include tax."
        )
    delivery_values = [float(r["delivery_days"]) for r in rows if r["delivery_days"] is not None]
    payment_values = [float(r["payment_days"]) for r in rows if r["payment_days"] is not None]
    reliability_values = [float(r["reliability"]) for r in rows if r["reliability"] is not None]

    # ------------------------------------------------------------------
    # Score each supplier
    # ------------------------------------------------------------------
    for row in rows:
        quotation = row["quotation"]
        missing: list[str] = []
        warnings: list[str] = []
        criteria: list[CriterionScore] = []

        # --- Price: lowest landed cost wins ---
        price_deductions: list[str] = []
        if row["landed"] is None:
            missing.append("total_cost")
            price_deductions.append("No total cost could be determined from this quotation.")
        elif not row["tax_included"] and any_tax_inclusive:
            # No tax figure was found. Whether the stated total already includes
            # tax is genuinely unknown, so say that rather than asserting it is
            # excluded - but still flag it, because if it IS excluded this
            # supplier looks cheaper than it is.
            missing.append("tax")
            price_deductions.append(
                "No tax amount or rate was found, so it is unclear whether this total includes tax. "
                "Other quotations here state one."
            )
            warnings.append(
                "Tax was not identified on this quotation; confirm whether the total is tax-inclusive "
                "before comparing it on price."
            )
        price_score = _lower_is_better(row["landed"], landed_values)
        criteria.append(
            CriterionScore(
                criterion="price",
                score=price_score,
                weight=weights["price"],
                weighted_score=round(price_score * weights["price"], 4),
                raw_value=row["landed"],
                unit=row["currency"],
                data_available=row["landed"] is not None,
                deductions=price_deductions,
            )
        )

        # --- Delivery: fewest days wins ---
        delivery_deductions: list[str] = []
        if row["delivery_days"] is None:
            missing.append("delivery_days")
            delivery_deductions.append("Delivery lead time was not stated.")
        delivery_score = _lower_is_better(
            float(row["delivery_days"]) if row["delivery_days"] is not None else None, delivery_values
        )
        criteria.append(
            CriterionScore(
                criterion="delivery",
                score=delivery_score,
                weight=weights["delivery"],
                weighted_score=round(delivery_score * weights["delivery"], 4),
                raw_value=float(row["delivery_days"]) if row["delivery_days"] is not None else None,
                unit="days",
                data_available=row["delivery_days"] is not None,
                deductions=delivery_deductions,
            )
        )

        # --- Payment terms: longer credit period is better for the buyer ---
        payment_deductions: list[str] = []
        if row["payment_days"] is None:
            missing.append("payment_terms")
            payment_deductions.append("Payment terms were not stated.")
        payment_score = _higher_is_better(
            float(row["payment_days"]) if row["payment_days"] is not None else None, payment_values
        )
        if row["payment_days"] == 0:
            payment_deductions.append("Advance payment required; no credit period.")
        criteria.append(
            CriterionScore(
                criterion="payment",
                score=payment_score,
                weight=weights["payment"],
                weighted_score=round(payment_score * weights["payment"], 4),
                raw_value=float(row["payment_days"]) if row["payment_days"] is not None else None,
                unit="days credit",
                data_available=row["payment_days"] is not None,
                deductions=payment_deductions,
            )
        )

        # --- Reliability: rule-based supplier score ---
        reliability_deductions: list[str] = []
        if row["reliability"] is None:
            missing.append("supplier_reliability")
            reliability_deductions.append("Supplier is not linked to a supplier record, so no reliability score.")
        # Reliability is already an absolute 0..1 score; use it directly rather
        # than normalising it away against the other suppliers.
        reliability_score = float(row["reliability"]) if row["reliability"] is not None else MISSING_DATA_SCORE
        criteria.append(
            CriterionScore(
                criterion="reliability",
                score=round(reliability_score, 4),
                weight=weights["reliability"],
                weighted_score=round(reliability_score * weights["reliability"], 4),
                raw_value=round(reliability_score, 4),
                unit="score",
                data_available=row["reliability"] is not None,
                deductions=reliability_deductions,
            )
        )

        # --- Other: completeness of the quotation itself ---
        other_deductions: list[str] = []
        coverage = row["coverage"]
        if coverage is None:
            coverage = (row["matched"] / requested_count) if requested_count else None
        if coverage is None:
            coverage_component = MISSING_DATA_SCORE
            other_deductions.append("Line items were not matched against the request.")
        else:
            coverage_component = float(coverage)
            if coverage < 1.0 and requested_count:
                other_deductions.append(
                    f"Quotes {row['matched']} of {requested_count} requested items."
                )

        validation = row["validation"] or {}
        errors = int(validation.get("error_count") or 0)
        warns = int(validation.get("warning_count") or 0)
        quality_component = max(0.0, 1.0 - (errors * 0.25) - (warns * 0.05))
        if errors:
            other_deductions.append(f"{errors} validation error(s) in the extracted data.")
        if warns:
            other_deductions.append(f"{warns} validation warning(s) in the extracted data.")

        other_score = round(coverage_component * 0.6 + quality_component * 0.4, 4)
        criteria.append(
            CriterionScore(
                criterion="other",
                score=other_score,
                weight=weights["other"],
                weighted_score=round(other_score * weights["other"], 4),
                raw_value=round(float(coverage), 4) if coverage is not None else None,
                unit="coverage",
                data_available=coverage is not None,
                deductions=other_deductions,
            )
        )

        overall = round(sum(c.weighted_score for c in criteria), 4)

        # Data completeness is reported separately so a high score built on thin
        # data is visible rather than flattering.
        available = sum(1 for c in criteria if c.data_available)
        completeness = round(available / len(criteria), 4)
        if completeness < 1.0:
            warnings.append(
                f"Scored on {available} of {len(criteria)} criteria; missing data was scored at "
                f"{MISSING_DATA_SCORE:.2f} rather than excluded."
            )

        anomaly_statuses = [
            (item.get("attributes") or {}).get("_price_anomaly", {}).get("status")
            for item in row["items"]
        ]
        anomaly_statuses = [s for s in anomaly_statuses if s]
        price_anomaly = worst_status(anomaly_statuses) if anomaly_statuses else None
        if price_anomaly in (AnomalyStatus.HIGH_ANOMALY.value, AnomalyStatus.POSSIBLE_ANOMALY.value):
            warnings.append(f"Price anomaly detected on at least one line item ({price_anomaly}).")

        result.suppliers.append(
            SupplierScore(
                quotation_id=str(quotation.get("id")),
                supplier_id=str(row["supplier_id"]) if row["supplier_id"] else None,
                supplier_name=row["supplier_name"],
                overall_score=overall,
                criteria=criteria,
                total_cost=row["subtotal"],
                landed_cost=row["landed"],
                currency=row["currency"],
                delivery_days=row["delivery_days"],
                payment_days=row["payment_days"],
                reliability_score=row["reliability"],
                coverage=round(float(coverage), 4) if coverage is not None else 0.0,
                matched_items=row["matched"],
                requested_items=requested_count,
                missing_data=missing,
                warnings=warnings,
                price_anomaly=price_anomaly,
                data_completeness=completeness,
            )
        )

    # ------------------------------------------------------------------
    # Rank. Ties break on data completeness, then on landed cost.
    # ------------------------------------------------------------------
    result.suppliers.sort(
        key=lambda s: (
            -s.overall_score,
            -s.data_completeness,
            s.landed_cost if s.landed_cost is not None else float("inf"),
        )
    )
    for position, supplier in enumerate(result.suppliers, start=1):
        supplier.rank = position

    if result.suppliers:
        top = result.suppliers[0]
        result.recommended_quotation_id = top.quotation_id
        result.recommended_supplier_name = top.supplier_name
        if top.data_completeness < 0.8:
            result.warnings.append(
                "The top-ranked quotation is missing data on one or more criteria; "
                "confirm the gaps before awarding."
            )
        if len(result.suppliers) > 1:
            runner_up = result.suppliers[1]
            if abs(top.overall_score - runner_up.overall_score) < 0.03:
                result.warnings.append(
                    f"'{top.supplier_name}' and '{runner_up.supplier_name}' are within 0.03 of each "
                    "other; the ranking between them is not decisive."
                )

    result.computed_at = datetime.now()
    return result
