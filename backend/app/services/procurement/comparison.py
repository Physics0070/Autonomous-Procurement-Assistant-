"""Supplier comparison engine.

Every number here is computed deterministically in Python. The AI is never
asked to rank, score, or weigh anything - it only receives the finished result
to describe in prose (see explanation.py).

Scoring is relative: each criterion is normalized across the suppliers being
compared, so a score answers "how does this quote compare with the others on
the table", which is the question a buyer is actually asking.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.schemas.comparison import ComparisonResult, CriterionScore, SupplierScore
from app.services.procurement.anomaly import AnomalyStatus, worst_status

logger = logging.getLogger(__name__)

# Penalty applied to a criterion when the underlying data is missing. Not zero:
# a missing value should hurt, but not eliminate an otherwise strong supplier.
MISSING_DATA_SCORE = 0.35
NEW_SUPPLIER_SCORE = 0.5
CRITERIA = ("price", "delivery", "payment", "reliability", "other")
# Arithmetic the supplier wrote on the document. Counted as the supplier's own error only once a person has explicitly
# confirmed that finding, field by field, against the document; until then it may just as well be a misreading by OCR
# or the model.
DOCUMENT_ARITHMETIC = {"line_total_mismatch", "subtotal_mismatch", "total_mismatch"}
TAX_TOLERANCE = (2.0, 0.005)
# Raised whenever the scoring rules change, so a comparison computed under older rules is stale for award.
COMPARISON_VERSION = 2  # 2: unknown GST basis beside known ones needs review; fingerprint covers scorecards and weights


def validate_weights(weights: Optional[dict[str, Any]]) -> dict[str, float]:
    """Only the supported criteria, each a finite number >= 0, and not all zero. Raises ValueError otherwise."""
    weights = weights or {}
    unknown = sorted(set(weights) - set(CRITERIA))
    if unknown:
        raise ValueError(f"Unknown criteria: {', '.join(unknown)}. Supported: {', '.join(CRITERIA)}.")
    out = {}
    for key, value in weights.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Weight for '{key}' must be a number of 0 or more.")
        out[key] = float(value)
    return out


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    weights = {k: max(float(weights.get(k, 0.0)), 0.0) for k in CRITERIA}
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("At least one criterion needs a weight above 0.")
    return {k: w / total for k, w in weights.items()}


def _close(a: float, b: float) -> bool:
    absolute, relative = TAX_TOLERANCE
    return abs(a - b) <= max(absolute, abs(b) * relative)


_INCLUSIVE_WORDING = re.compile(
    r"\b(incl(?:\.|usive|uding)?\s*(?:of\s*)?(?:all\s*)?(?:gst|taxes|tax)\b|(?:gst|taxes|tax)\s*incl(?:\.|uded|usive)?)",
    re.IGNORECASE)
_EXTRA_WORDING = re.compile(
    r"\b((?:gst|igst|cgst|taxes|tax)\s*(?:@?\s*\d+(?:\.\d+)?\s*%?\s*)?(?:extra|additional|as applicable|will be charged|excluded|exclusive)"
    r"|plus\s*(?:gst|taxes)|excl(?:\.|uding|usive)?\s*(?:of\s*)?(?:gst|taxes|tax))|\+\s*gst\b",
    re.IGNORECASE)


def gst_wording(text: Optional[str]) -> Optional[str]:
    """What the document says about GST: inclusive, extra, or None when it says neither (or both)."""
    text = text or ""
    inclusive, extra = bool(_INCLUSIVE_WORDING.search(text)), bool(_EXTRA_WORDING.search(text))
    return "inclusive" if inclusive and not extra else "extra" if extra and not inclusive else None


def tax_basis(data: dict[str, Any], text: Optional[str] = None) -> tuple[str, Optional[float], Optional[str]]:
    """Whether the quoted total includes GST: (inclusive | exclusive | unknown, tax-inclusive total, note).

    Figures that reconcile come first: a printed total equal to net subtotal + GST (+ freight) is inclusive. A total
    equal to the net subtotal (+ freight) is ambiguous - "rates inclusive of GST" or "GST extra" - so the document's
    own wording decides; with no wording and a GST rate stated it is taken as GST extra and GST is added. A GST rate
    on its own never shows that a total includes it.
    """
    wording = gst_wording(text)
    pricing = data.get("pricing") or {}
    landed = pricing.get("landed_total") if pricing.get("landed_total") is not None else pricing.get("total_amount")
    printed, gross = pricing.get("total_amount"), pricing.get("subtotal")
    net = gross - (pricing.get("discount_amount") or 0) if gross is not None else None
    freight = pricing.get("transportation_cost") or 0.0
    tax = pricing.get("tax_amount")
    if tax is None and net is not None and pricing.get("tax_percentage") is not None:
        tax = net * pricing["tax_percentage"] / 100
    if tax is None and net is not None and gross:
        rated = [(i.get("total_price") if i.get("total_price") is not None else i.get("computed_total"), i.get("tax_percentage"))
                 for i in data.get("items") or []]
        if rated and all(t is not None and r is not None for t, r in rated):
            tax = sum(t * r / 100 for t, r in rated) * (net / gross)  # line GST rates, after the discount share
    if printed is None:
        if wording == "inclusive":
            return "inclusive", landed, "The quotation states its prices include GST."
        if net is not None and tax is not None:
            return "inclusive", landed, "Total worked out from the subtotal and GST."
        if wording == "extra":
            return "exclusive", None, "The quotation says GST is extra but gives no rate, so its GST-inclusive price is unknown."
        return "unknown", landed, None
    if net is None:
        return "unknown", printed, None
    if tax and any(_close(printed, net + tax + f) for f in {freight, 0.0}):
        return "inclusive", printed, None
    if any(_close(printed, net + f) for f in {freight, 0.0}):
        if wording == "inclusive":
            return "inclusive", printed, "The quotation states its prices include GST."
        if tax:
            return "exclusive", round(printed + tax, 2), f"GST of {round(tax, 2):,.2f} added: the quoted total excludes it."
        if wording == "extra":
            return "exclusive", None, "The quotation says GST is extra but gives no rate, so its GST-inclusive price is unknown."
        if tax == 0:
            return "inclusive", printed, "No GST applies."
    return "unknown", printed, None


def _aware(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return None


def _touches(path: str, field: str) -> bool:
    return bool(path) and (path == field or path.startswith(field + ".") or field.startswith(path + "."))


def _issue_origin(quotation: dict[str, Any], validation: dict[str, Any]) -> tuple[list[str], int]:
    """(supplier arithmetic errors confirmed on the document, count of unverified issues).

    Confirmed: an arithmetic finding a person explicitly confirmed for that field and code (`confirmed_issues`),
    with no correction of that field since. A correction of some other field confirms nothing. Everything else may
    be a reading error by OCR or the model and is never scored.
    """
    confirmations = {(c.get("field"), c.get("code")): _aware(c.get("confirmed_at"))
                     for c in quotation.get("confirmed_issues") or []}
    corrections = [(c.get("path") or "", _aware(c.get("corrected_at"))) for c in quotation.get("user_corrections") or []]
    confirmed, unverified = [], 0
    for issue in validation.get("issues") or []:
        key = (issue.get("field"), issue.get("code"))
        field = (issue.get("field") or "").replace("commercials.", "pricing.")
        valid = issue.get("code") in DOCUMENT_ARITHMETIC and key in confirmations
        if valid:
            at = confirmations[key]
            # A later correction of the same figure means it was a misreading after all (or the time is unknown).
            valid = not any(_touches(path, field) and (when is None or at is None or when > at) for path, when in corrections)
        if valid:
            confirmed.append(issue.get("message") or issue.get("code"))
        else:
            unverified += 1
    return confirmed, unverified


SCORECARD_FIELDS = ("method", "version", "score", "status", "coverage", "band")


def comparison_fingerprint(request: dict[str, Any], quotations: list[dict[str, Any]],
                           suppliers_by_id: Optional[dict[str, dict[str, Any]]] = None) -> str:
    """A digest of everything the comparison is computed from: the scoring rules' version, the configured default
    weights, the requested items, every quotation on the request (its data, matching, status, findings and
    confirmations) and the performance scorecard of each quoting supplier. Any change, or a quotation added or
    removed, changes it, so an award can tell that a stored comparison no longer describes its inputs."""
    suppliers_by_id = suppliers_by_id or {}
    scorecards = {}
    for q in quotations:
        sid = str(q.get("supplier_id") or "")
        if sid:
            card = (suppliers_by_id.get(sid) or {}).get("reliability") if sid in suppliers_by_id else None
            scorecards[sid] = None if sid not in suppliers_by_id else {k: (card or {}).get(k) for k in SCORECARD_FIELDS}
    material = {
        "version": COMPARISON_VERSION,
        "default_weights": settings.scoring_weights(),
        "scorecards": scorecards,
        "request": {"items": request.get("items"), "currency": request.get("currency")},
        "quotations": sorted(([
            str(q.get("id")), q.get("processing_status"), str(q.get("supplier_id") or ""),
            q.get("effective_data") or q.get("normalized_data"), q.get("match_result"), q.get("validation"),
            q.get("confirmed_issues"), (q.get("raw_content") or {}).get("raw_text"),
        ] for q in quotations), key=lambda item: item[0]),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


NO_SPREAD_SCORE = 0.5  # a relative score needs at least two different values; otherwise it says nothing


def _no_spread(values: list[float]) -> Optional[str]:
    if len(values) < 2:
        return "Only one quotation states this, so there is nothing to compare it with; scored neutral."
    if max(values) == min(values):
        return "The quotations are all the same on this, so it does not separate them; scored neutral."
    return None


def _lower_is_better(value: Optional[float], values: list[float]) -> float:
    """Normalize so the smallest value scores 1.0 and the largest 0.0."""
    if value is None or not values:
        return MISSING_DATA_SCORE
    if _no_spread(values):
        return NO_SPREAD_SCORE
    low, high = min(values), max(values)
    return round(1.0 - (value - low) / (high - low), 4)


def _higher_is_better(value: Optional[float], values: list[float]) -> float:
    if value is None or not values:
        return MISSING_DATA_SCORE
    if _no_spread(values):
        return NO_SPREAD_SCORE
    low, high = min(values), max(values)
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
    weights = _normalize_weights({**settings.scoring_weights(), **validate_weights(weight_overrides)})

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
        scorecard = (supplier_doc or {}).get("reliability") or {}
        reliability = scorecard.get("score")
        basis, comparable_price, tax_note = tax_basis(data, (quotation.get("raw_content") or {}).get("raw_text"))

        landed = pricing.get("landed_total")
        if landed is None:
            landed = pricing.get("total_amount")
        subtotal = pricing.get("subtotal")
        if subtotal is not None and pricing.get("discount_amount"):
            subtotal = round(subtotal - pricing["discount_amount"], 2)

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
                "transport": pricing.get("transportation_cost"),
                "tax_basis": basis,
                "comparable_price": comparable_price,
                "tax_note": tax_note,
                "delivery_days": delivery.get("delivery_days"),
                "payment_days": payment_days,
                "reliability": reliability,
                "reliability_status": ("unlinked" if not supplier_doc else "new" if reliability is None
                                       else scorecard.get("status") or "rated"),
                "reliability_coverage": scorecard.get("coverage"),
                "reliability_band": scorecard.get("band"),
                "reliability_reasons": scorecard.get("reasons") or [],
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

    # Prices are compared only in the request's currency; a quotation in another currency is never put on the same
    # scale without an exchange rate, and is held back from the recommendation.
    other_currency = [r for r in rows if r["currency"] and r["currency"] != currency]
    if other_currency:
        result.warnings.append(
            f"{len(other_currency)} quotation(s) are not in {currency} "
            f"({', '.join(sorted({r['currency'] for r in other_currency}))}); they are not compared on price "
            "and need review before award."
        )
    foreign = {id(r) for r in other_currency}
    in_currency = [r for r in rows if id(r) not in foreign and r["comparable_price"] is not None]
    known = [r for r in in_currency if r["tax_basis"] != "unknown"]
    # GST-inclusive totals are compared with GST-inclusive totals; a total whose basis is unknown is never ranked
    # against them. When no quotation shows its basis, raw totals could mix GST-inclusive and GST-extra figures, so
    # none is ranked on price and every one needs review: the quoted totals are shown, not scored.
    priced = known
    gst_unranked = bool(in_currency) and not known
    unranked_ids = {id(r) for r in in_currency} if gst_unranked else set()
    if gst_unranked:
        result.warnings.append("No quotation shows whether its total includes GST, so the quoted totals are not ranked "
                               "on price. Confirm the GST treatment of each before awarding.")
    landed_values = [r["comparable_price"] for r in priced]
    priced_ids = {id(r) for r in priced}
    delivery_values = [float(r["delivery_days"]) for r in rows if r["delivery_days"] is not None]
    payment_values = [float(r["payment_days"]) for r in rows if r["payment_days"] is not None]

    # ------------------------------------------------------------------
    # Score each supplier
    # ------------------------------------------------------------------
    for row in rows:
        quotation = row["quotation"]
        missing: list[str] = []
        warnings: list[str] = []
        criteria: list[CriterionScore] = []

        # --- Price: lowest comparable (GST-inclusive) cost wins ---
        price_deductions: list[str] = []
        review_reasons: list[str] = []
        in_scale = id(row) in priced_ids
        if id(row) in foreign:
            missing.append("total_cost")
            price_deductions.append(f"Quoted in {row['currency']}; not compared with {currency} prices.")
            review_reasons.append(f"Quoted in {row['currency']}: convert to {currency} before comparing or awarding.")
        elif row["comparable_price"] is None:
            missing.append("tax" if row["tax_basis"] == "exclusive" else "total_cost")
            price_deductions.append(row["tax_note"] or "No total cost could be determined from this quotation.")
        elif id(row) in unranked_ids:
            missing.append("tax")
            price_deductions.append(f"Quoted total {row['comparable_price']:,.2f} is shown but not ranked: no quotation "
                                    "here shows whether its total includes GST. Scored neutral.")
            review_reasons.append("Confirm whether the quoted total includes GST before awarding; no quotation here "
                                  "shows it, so prices could not be compared.")
        elif not in_scale:
            missing.append("tax")
            price_deductions.append("Not compared on price: the figures do not show whether this total includes GST, "
                                    "while other quotations here do.")
            warnings.append("Confirm whether this total includes GST before comparing it on price.")
            review_reasons.append("Confirm whether this quoted total includes GST before awarding; the other "
                                  "quotations here show theirs, so it could not be compared with them on price.")
        if row["tax_note"] and in_scale:
            price_deductions.append(row["tax_note"])
        price_value = row["comparable_price"] if in_scale else None
        price_score = NO_SPREAD_SCORE if id(row) in unranked_ids else _lower_is_better(price_value, landed_values)
        if price_value is not None and _no_spread(landed_values):
            price_deductions.append(_no_spread(landed_values))
        criteria.append(
            CriterionScore(
                criterion="price",
                score=price_score,
                weight=weights["price"],
                weighted_score=round(price_score * weights["price"], 4),
                raw_value=price_value,
                unit=row["currency"],
                data_available=price_value is not None,
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
        if row["delivery_days"] is not None and _no_spread(delivery_values):
            delivery_deductions.append(_no_spread(delivery_values))
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
        if row["payment_days"] is not None and _no_spread(payment_values):
            payment_deductions.append(_no_spread(payment_values))
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

        # --- Reliability: the supplier's performance scorecard ---
        reliability_deductions: list[str] = []
        if row["reliability_status"] == "unlinked":
            missing.append("supplier_reliability")
            reliability_deductions.append("Supplier is not linked to a supplier record, so no performance score.")
            reliability_score = MISSING_DATA_SCORE
        elif row["reliability_status"] == "new":
            # Too few orders to judge: neutral, neither rewarded nor punished for being new.
            reliability_deductions.append("New supplier: too few orders for a performance score yet.")
            reliability_score = NEW_SUPPLIER_SCORE
        elif row["reliability_status"] == "provisional":
            # Thin evidence moves the score only part of the way from neutral, in proportion to what is recorded.
            coverage_share = min(max(float(row["reliability_coverage"] or 0.0), 0.0), 1.0)
            reliability_score = NEW_SUPPLIER_SCORE + (float(row["reliability"]) - NEW_SUPPLIER_SCORE) * coverage_share
            reliability_deductions.append(
                f"Provisional score {float(row['reliability']):.2f} from limited records ({coverage_share:.0%} of the "
                f"scorecard); counted as {reliability_score:.2f}, part way from neutral.")
        else:
            # Already an absolute 0..1 score; used directly rather than normalised against the other suppliers.
            reliability_score = float(row["reliability"])
        criteria.append(
            CriterionScore(
                criterion="reliability",
                score=round(reliability_score, 4),
                weight=weights["reliability"],
                weighted_score=round(reliability_score * weights["reliability"], 4),
                raw_value=round(reliability_score, 4),
                unit="score",
                data_available=row["reliability_status"] == "rated",
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

        # Validation findings are never scored: until a person confirms them they may be our own reading errors.
        confirmed, unverified = _issue_origin(quotation, row["validation"] or {})
        if unverified:
            warnings.append(f"{unverified} extracted figure(s) need checking; they may be reading errors and do not "
                            "count against the supplier.")
        for message in confirmed:
            warnings.append(f"Supplier's own error, confirmed on review: {message}")

        other_score = round(coverage_component, 4)
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
        if price_anomaly == AnomalyStatus.HIGH_ANOMALY.value:
            review_reasons.append("A price is far outside this item's usual range: check it before awarding.")

        result.suppliers.append(
            SupplierScore(
                quotation_id=str(quotation.get("id")),
                supplier_id=str(row["supplier_id"]) if row["supplier_id"] else None,
                supplier_name=row["supplier_name"],
                overall_score=overall,
                criteria=criteria,
                total_cost=row["subtotal"],
                landed_cost=row["landed"],
                transport_cost=row["transport"],
                currency=row["currency"],
                delivery_days=row["delivery_days"],
                payment_days=row["payment_days"],
                reliability_score=row["reliability"],
                reliability_status=row["reliability_status"],
                reliability_band=row["reliability_band"],
                reliability_reasons=row["reliability_reasons"],
                tax_basis=row["tax_basis"],
                comparable_price=row["comparable_price"],
                requires_review=bool(review_reasons),
                review_reasons=review_reasons,
                confirmed_supplier_errors=confirmed,
                unverified_issues=unverified,
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
        # The recommendation is the best-ranked quotation that can be awarded as it stands, not simply the top score.
        awardable = [s for s in result.suppliers if not s.requires_review]
        first = result.suppliers[0]
        if first.requires_review:
            result.warnings.append(f"'{first.supplier_name}' ranks first but needs review before award: "
                                   + " ".join(first.review_reasons))
        if not awardable:
            result.warnings.append("No quotation can be recommended until the review points above are resolved.")
            return _finish(result)
        top = awardable[0]
        result.recommended_quotation_id = top.quotation_id
        result.recommended_supplier_name = top.supplier_name
        if top.data_completeness < 0.8:
            result.warnings.append(
                "The top-ranked quotation is missing data on one or more criteria; "
                "confirm the gaps before awarding."
            )
        if len(result.suppliers) > 1:
            runner_up = result.suppliers[1]
            if abs(first.overall_score - runner_up.overall_score) < 0.03:
                result.warnings.append(
                    f"'{first.supplier_name}' and '{runner_up.supplier_name}' are within 0.03 of each "
                    "other; the ranking between them is not decisive."
                )

    return _finish(result)


def _finish(result: ComparisonResult) -> ComparisonResult:
    result.computed_at = datetime.now()
    return result
