"""Prompt templates.

The single most important rule in this file is the no-invention rule: the model
must return null instead of guessing. It is stated in the system instruction,
repeated in the task instruction, and enforced afterwards by Pydantic and the
validation service.
"""
from __future__ import annotations

import json

NO_INVENTION_RULE = (
    "Extract only information supported by the source. "
    "If a value is unavailable or uncertain, return null rather than guessing."
)

EXTRACTION_SYSTEM = f"""You are a procurement document extraction engine for an SME procurement platform.
You read messy supplier quotations - digital PDFs, scanned pages run through OCR, spreadsheets,
and multilingual documents - and return strict JSON.

CRITICAL RULES
1. {NO_INVENTION_RULE}
2. Never calculate, infer, or complete a value that is not present in the source.
   Do not compute totals, do not derive unit prices from totals, do not assume tax rates.
3. Copy product descriptions exactly as written in the source, including the original
   language, spelling, punctuation and units. Do not translate or tidy them.
4. If the document is OCR output it may contain errors such as missing spaces or merged
   numbers. Do not silently repair them into plausible values. If a number is unreadable
   or ambiguous, return null and mention it in "notes".
5. Return ONLY a JSON object. No markdown fences, no commentary.
"""

EXTRACTION_SCHEMA = {
    "supplier": {
        "name": "string or null",
        "email": "string or null",
        "phone": "string or null",
        "gst_number": "string or null",
        "address": "string or null",
    },
    "quotation": {
        "reference": "string or null",
        "date": "string or null (copy exactly as printed)",
        "validity": "string or null",
        "currency": "string or null (ISO code if determinable, e.g. INR)",
    },
    "items": [
        {
            "original_name": "string or null (verbatim from the document)",
            "quantity": "number or null",
            "unit": "string or null (verbatim, e.g. Nos, PCS, BOTTLE)",
            "unit_price": "number or null",
            "gst_percentage": "number or null",
            "total_price": "number or null",
            "attributes": {"any_extra_column_name": "value"},
        }
    ],
    "commercials": {
        "subtotal": "number or null",
        "tax_amount": "number or null",
        "tax_percentage": "number or null",
        "total_amount": "number or null",
        "transportation_cost": "number or null",
        "delivery_days": "integer or null",
        "delivery_terms": "string or null",
        "payment_terms": "string or null",
        "payment_days": "integer or null",
        "warranty": "string or null",
    },
    "additional_attributes": {"any_other_useful_field": "value"},
    "notes": ["short strings describing anything unreadable or ambiguous"],
}


def build_extraction_prompt(document_text: str, *, document_type: str, language: str | None, ocr_used: bool) -> str:
    ocr_warning = (
        "\nThis text came from OCR and may contain recognition errors. Apply rule 4 strictly.\n"
        if ocr_used
        else ""
    )
    return f"""Extract the supplier quotation below into JSON matching this exact shape:

{json.dumps(EXTRACTION_SCHEMA, indent=2)}

Document type: {document_type}
Detected language: {language or "unknown"}{ocr_warning}

Reminder: {NO_INVENTION_RULE}
Use null for every field you cannot support with text from the document.
"items" must contain one entry per line item actually listed. If no line items are
present, return an empty list.

===== BEGIN DOCUMENT =====
{document_text}
===== END DOCUMENT =====

Return the JSON object only."""


# ---------------------------------------------------------------------------
# Product matching (only invoked for genuinely ambiguous pairs)
# ---------------------------------------------------------------------------

MATCHING_SYSTEM = f"""You decide whether two procurement product descriptions refer to the same product.
You are used only for cases that deterministic and fuzzy matching could not resolve.

RULES
1. {NO_INVENTION_RULE}
2. Judge only from the descriptions given. Do not assume specifications that are not written.
3. A difference in size, class, grade, material or rating means they are NOT the same product.
4. Return ONLY JSON.
"""


def build_matching_prompt(requested: str, candidates: list[dict]) -> str:
    listing = "\n".join(
        f'{i}. id="{c["id"]}" description="{c["name"]}" unit="{c.get("unit") or "unknown"}"'
        for i, c in enumerate(candidates)
    )
    return f"""Requested item:
"{requested}"

Candidate quotation line items:
{listing}

Which candidate, if any, is the same product as the requested item?

Return JSON:
{{
  "match_id": "the id of the matching candidate, or null if none match",
  "confidence": 0.0,
  "reason": "one short sentence"
}}

Set match_id to null if no candidate is clearly the same product.
Confidence must be between 0 and 1 and must reflect genuine certainty."""


# ---------------------------------------------------------------------------
# Recommendation explanation (explains scores; never computes them)
# ---------------------------------------------------------------------------

EXPLANATION_SYSTEM = f"""You explain a procurement supplier ranking that has ALREADY been calculated
by a deterministic scoring engine.

RULES
1. {NO_INVENTION_RULE}
2. You MUST NOT recalculate, re-rank, or contradict the supplied scores. The ranking is final.
3. Refer only to the numbers provided. Never introduce a figure that is not in the input.
4. If data is flagged as missing, describe it as missing - do not fill it in.
5. Return ONLY JSON.
"""


def build_explanation_prompt(payload: dict) -> str:
    return f"""Here is a completed supplier comparison for a procurement request.
Scores, weights and the ranking were computed deterministically and are final.

{json.dumps(payload, indent=2, default=str)}

Write a short procurement-manager-facing explanation of this ranking.

Return JSON:
{{
  "summary": "2-3 sentences on why the top-ranked supplier ranks first",
  "reasoning": ["3-5 bullet points citing the supplied criterion scores and values"],
  "risks": ["risks, missing data, or caveats a buyer should check before awarding"]
}}

Reminder: explain the given ranking. Do not compute a different one."""
