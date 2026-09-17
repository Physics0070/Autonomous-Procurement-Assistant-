"""Supplier reliability scoring.

This is an explicitly RULE-BASED score, not a machine-learning prediction.
`method` is reported on every result so the UI can say so honestly. The shape
of the output is designed so an ML model can later replace or augment the
rule set without changing any caller.
"""
from __future__ import annotations

from typing import Any, Optional

# Neutral prior for a supplier with no history. Deliberately mid-scale so a new
# supplier is neither rewarded nor punished for being new.
NEUTRAL_SCORE = 0.5

# Weight of each rule inside the reliability score.
RULE_WEIGHTS = {
    "profile_completeness": 0.30,
    "quotation_history": 0.25,
    "data_quality": 0.25,
    "responsiveness": 0.20,
}


def compute_reliability(
    supplier: dict[str, Any],
    *,
    quotations: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Score a supplier from the information actually available.

    Returns the score plus the factors behind it, so the number is explainable
    rather than opaque.
    """
    quotations = quotations or []
    notes: list[str] = []
    factors: dict[str, Any] = {}

    # --- Rule 1: profile completeness (a verifiable, contactable supplier) ---
    fields = ("email", "phone", "gst_number", "address")
    present = sum(1 for f in fields if supplier.get(f))
    completeness = present / len(fields)
    factors["profile_completeness"] = {
        "score": round(completeness, 3),
        "present_fields": present,
        "total_fields": len(fields),
    }
    if completeness < 1.0:
        missing = [f for f in fields if not supplier.get(f)]
        notes.append(f"Supplier profile is missing: {', '.join(missing)}.")

    # --- Rule 2: quotation history (engagement depth) ---
    count = len(quotations)
    # Saturates at 5 quotations; beyond that extra history adds little signal.
    history = min(count / 5.0, 1.0)
    factors["quotation_history"] = {"score": round(history, 3), "quotation_count": count}
    if count == 0:
        notes.append("No quotation history yet; reliability is based on profile data alone.")

    # --- Rule 3: data quality of the quotations received ---
    if quotations:
        clean = 0
        for quotation in quotations:
            validation = quotation.get("validation") or {}
            errors = validation.get("error_count", 0) or 0
            warnings = validation.get("warning_count", 0) or 0
            if errors == 0 and warnings <= 2:
                clean += 1
        quality = clean / len(quotations)
        factors["data_quality"] = {
            "score": round(quality, 3),
            "clean_quotations": clean,
            "total_quotations": len(quotations),
        }
        if quality < 0.5:
            notes.append("Most quotations from this supplier required corrections.")
    else:
        quality = NEUTRAL_SCORE
        factors["data_quality"] = {"score": quality, "reason": "no_history"}

    # --- Rule 4: responsiveness (did quotations reach a usable state) ---
    if quotations:
        completed = sum(
            1 for q in quotations if q.get("processing_status") in ("COMPLETED", "REQUIRES_REVIEW")
        )
        responsiveness = completed / len(quotations)
        factors["responsiveness"] = {
            "score": round(responsiveness, 3),
            "usable_quotations": completed,
            "total_quotations": len(quotations),
        }
    else:
        responsiveness = NEUTRAL_SCORE
        factors["responsiveness"] = {"score": responsiveness, "reason": "no_history"}

    score = (
        completeness * RULE_WEIGHTS["profile_completeness"]
        + history * RULE_WEIGHTS["quotation_history"]
        + quality * RULE_WEIGHTS["data_quality"]
        + responsiveness * RULE_WEIGHTS["responsiveness"]
    )

    return {
        "score": round(min(max(score, 0.0), 1.0), 4),
        "method": "rule_based",
        "sample_size": count,
        "factors": factors,
        "notes": notes or ["Reliability derived from available profile and quotation history."],
        "weights": RULE_WEIGHTS,
        "is_ml_prediction": False,
    }
