"""AI structured extraction: ProcessedDocument -> validated AIExtractionResult.

Two guarantees this module upholds:
  * a missing/failed AI provider degrades gracefully into a heuristic
    extraction that is clearly labelled as such, and
  * whatever the model returns is forced through Pydantic before it is
    allowed anywhere near the rest of the system.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import ValidationError as PydanticValidationError

from app.core.gstin import GSTIN_SEARCH_RE
from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import get_ai_provider
from app.integrations.ai.prompts import EXTRACTION_SYSTEM, build_extraction_prompt
from app.schemas.document import ProcessedDocument
from app.schemas.extraction import AIExtractionResult

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def parse_json_response(text: str) -> tuple[Optional[dict], Optional[str]]:
    """Parse model output into a dict, tolerating fences and trailing prose."""
    cleaned = _strip_code_fences(text)
    try:
        data = json.loads(cleaned)
        return (data, None) if isinstance(data, dict) else (None, "Response was not a JSON object")
    except json.JSONDecodeError:
        pass
    # Fall back to the outermost {...} block.
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data, None
        except json.JSONDecodeError as exc:
            return None, f"Could not parse JSON: {exc}"
    return None, "No JSON object found in response"


async def extract_structured(
    document: ProcessedDocument, provider: Optional[AIProvider] = None
) -> tuple[AIExtractionResult, Optional[str]]:
    """Returns (result, error). `error` is set when AI could not be used.

    Even on error a result is returned - built by the heuristic fallback - so
    the pipeline continues and the user still sees something reviewable.
    """
    provider = provider or get_ai_provider()
    now = datetime.now(timezone.utc).isoformat()

    text = document.text_for_ai()
    if not text.strip():
        result = AIExtractionResult(
            provider="none",
            extracted_at=now,
            notes=["Document produced no text or tables, so nothing could be extracted."],
        )
        return result, "Empty document"

    if not provider.is_configured():
        reason = provider.configuration_error() or "AI provider is not configured."
        logger.warning("AI extraction unavailable: %s", reason)
        result = heuristic_extraction(document)
        result.extracted_at = now
        result.notes.insert(0, f"AI provider unavailable: {reason}")
        result.notes.append(
            "Values below came from a deterministic heuristic parser, not from an AI model. "
            "Review them before use."
        )
        return result, reason

    prompt = build_extraction_prompt(
        text,
        document_type=document.document_type.value,
        language=document.detected_language,
        ocr_used=document.ocr_used,
    )
    response = await provider.generate(prompt, system=EXTRACTION_SYSTEM, json_mode=True, temperature=0.0)

    if not response.ok:
        logger.warning("AI extraction call failed: %s", response.error)
        result = heuristic_extraction(document)
        result.extracted_at = now
        result.notes.insert(0, f"AI extraction failed: {response.error}")
        return result, response.error

    data, parse_error = parse_json_response(response.text)
    if data is None:
        result = heuristic_extraction(document)
        result.extracted_at = now
        result.raw_response = response.text[:20000]
        result.notes.insert(0, f"AI returned unparseable output: {parse_error}")
        return result, parse_error

    # Pydantic is the gate. Anything that does not fit the contract is rejected.
    try:
        result = AIExtractionResult.model_validate(data)
    except PydanticValidationError as exc:
        salvaged = _salvage(data)
        try:
            result = AIExtractionResult.model_validate(salvaged)
            result.notes.append(f"Some AI fields failed validation and were dropped: {exc.error_count()} error(s)")
        except PydanticValidationError:
            result = heuristic_extraction(document)
            result.notes.insert(0, "AI output failed schema validation entirely; used heuristic fallback.")
            result.extracted_at = now
            result.raw_response = response.text[:20000]
            return result, f"AI output failed validation: {exc.error_count()} error(s)"

    result.provider = response.provider
    result.model = response.model
    result.extracted_at = now
    result.raw_response = response.text[:20000]
    if response.meta:
        result.additional_attributes.setdefault("_usage", response.meta)
    return result, None


def _salvage(data: dict) -> dict:
    """Keep the parts of an AI response that fit, discard the parts that do not."""
    out: dict[str, Any] = {}
    for key in ("supplier", "quotation", "commercials", "additional_attributes"):
        if isinstance(data.get(key), dict):
            out[key] = data[key]
    items = data.get("items")
    if isinstance(items, list):
        out["items"] = [i for i in items if isinstance(i, dict)]
    notes = data.get("notes")
    if isinstance(notes, list):
        out["notes"] = [str(n) for n in notes]
    return out


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?\b\d{5}[\s-]?\d{5}\b|\b0\d{2,4}[\s-]?\d{6,8}\b")
_GST_RE = GSTIN_SEARCH_RE
# Must stay on one line and the captured reference must contain a digit,
# otherwise a bare "QUOTATION" heading is mistaken for the reference itself.
_REF_RE = re.compile(
    r"(?:quotation|quote|qtn|ref(?:erence)?)[ \t]*"
    r"(?:no|number|ref|#)?[ \t]*[:.\-][ \t]*"
    r"([A-Za-z0-9][A-Za-z0-9/\-_]{2,30})",
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})\b")
_TOTAL_RE = re.compile(
    r"(?:grand\s*total|net\s*payable|total\s*amount|nett?\s*total)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_SUBTOTAL_RE = re.compile(
    r"(?:sub\s*total|basic\s*amount|taxable\s*value)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
# Accepts "GST 18%", "GST @ 18 %" and the OCR-friendly "GST 18 percent".
_TAX_RE = re.compile(
    r"(?:gst|tax|igst|cgst|vat)\s*@?\s*(\d{1,2}(?:\.\d+)?)\s*(?:%|(?:percent|pct)\b)",
    re.IGNORECASE,
)
_TAX_AMT_RE = re.compile(
    r"(?:gst|tax)[^\n\d]{0,20}?(?:@\s*\d{1,2}(?:\.\d+)?\s*%)?[^\n\d]{0,10}?([\d,]+\.\d{2})", re.IGNORECASE
)
_FREIGHT_RE = re.compile(
    r"(?:transport(?:ation)?|freight|carriage|delivery\s*charge)\s*[:\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
_DELIVERY_DAYS_RE = re.compile(
    r"deliver(?:y|ed)?[^\n.]{0,40}?(\d{1,3})\s*(?:-|to|–)?\s*(\d{1,3})?\s*(?:working\s*)?days",
    re.IGNORECASE,
)
_PAYMENT_DAYS_RE = re.compile(r"(\d{1,3})\s*days?\s*(?:credit|from\s*(?:the\s*)?date\s*of\s*invoice)", re.IGNORECASE)
_PAYMENT_DAYS_ALT_RE = re.compile(r"payment[^\n.]{0,40}?(\d{1,3})\s*days", re.IGNORECASE)
_ADVANCE_RE = re.compile(r"(\d{1,3})\s*%\s*advance", re.IGNORECASE)
_VALIDITY_RE = re.compile(r"valid(?:ity)?[^\n.]{0,30}?(\d{1,3})\s*days", re.IGNORECASE)


_WHITESPACE_MAP = {
    " ": " ",  # non-breaking space
    " ": " ",  # figure space
    " ": " ",  # narrow no-break space
    " ": " ",  # thin space
    "​": "",   # zero-width space
    "﻿": "",   # byte-order mark
}


def normalize_whitespace(text: str) -> str:
    """PDF text often carries exotic spaces that break naive tokenisation."""
    for source, target in _WHITESPACE_MAP.items():
        text = text.replace(source, target)
    return text


def _num(value: str | None) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def heuristic_extraction(document: ProcessedDocument) -> AIExtractionResult:
    """Regex/table extraction used when AI is unavailable.

    This is deliberately conservative: it fills a field only when the pattern
    is unambiguous, and it is always labelled so nobody mistakes it for AI
    output. It is a graceful degradation, not a replacement.
    """
    # PDF text often carries non-breaking / thin spaces that break tokenisation.
    text = normalize_whitespace(document.raw_text or "")
    result = AIExtractionResult(provider="heuristic", model="regex+table")

    # --- Supplier ---
    email = _EMAIL_RE.search(text)
    phone = _PHONE_RE.search(text)
    gst = _GST_RE.search(text)
    result.supplier.email = email.group(0) if email else None
    result.supplier.phone = phone.group(0).strip() if phone else None
    result.supplier.gst_number = gst.group(0).upper() if gst else None

    # The supplier name is normally the first substantial line of the document.
    for line in text.splitlines():
        candidate = line.strip().lstrip("-").strip()
        if candidate.startswith("--- Page") or candidate.startswith("=== Sheet"):
            continue
        if len(candidate) >= 6 and not candidate.lower().startswith(("quotation", "quote", "date")):
            letters = sum(1 for c in candidate if c.isalpha())
            if letters >= 5:
                result.supplier.name = candidate[:200]
                break

    # --- Quotation meta ---
    for candidate in _REF_RE.finditer(text):
        value = candidate.group(1)
        if any(ch.isdigit() for ch in value):
            result.quotation.reference = value
            break
    date = _DATE_RE.search(text)
    if date:
        result.quotation.date = date.group(1)
    validity = _VALIDITY_RE.search(text)
    if validity:
        result.quotation.validity = f"{validity.group(1)} days"
    if "₹" in text or re.search(r"\b(INR|Rs\.?)\b", text, re.IGNORECASE):
        result.quotation.currency = "INR"

    # --- Commercials ---
    total = _TOTAL_RE.search(text)
    result.commercials.total_amount = _num(total.group(1)) if total else None
    subtotal = _SUBTOTAL_RE.search(text)
    result.commercials.subtotal = _num(subtotal.group(1)) if subtotal else None
    tax_pct = _TAX_RE.search(text)
    result.commercials.tax_percentage = _num(tax_pct.group(1)) if tax_pct else None
    tax_amt = _TAX_AMT_RE.search(text)
    if tax_amt:
        result.commercials.tax_amount = _num(tax_amt.group(1))
    freight = _FREIGHT_RE.search(text)
    result.commercials.transportation_cost = _num(freight.group(1)) if freight else None

    delivery = _DELIVERY_DAYS_RE.search(text)
    if delivery:
        # For "10-12 days" take the pessimistic end, which is what a buyer plans against.
        lo, hi = delivery.group(1), delivery.group(2)
        days = _num(hi) if hi else _num(lo)
        result.commercials.delivery_days = int(days) if days is not None else None
        result.commercials.delivery_terms = delivery.group(0).strip()

    payment = _PAYMENT_DAYS_RE.search(text) or _PAYMENT_DAYS_ALT_RE.search(text)
    if payment:
        result.commercials.payment_days = int(float(payment.group(1)))
    advance = _ADVANCE_RE.search(text)
    if advance:
        result.commercials.payment_terms = advance.group(0).strip()
        if result.commercials.payment_days is None:
            result.commercials.payment_days = 0  # advance payment = no credit period
    elif payment:
        result.commercials.payment_terms = payment.group(0).strip()

    # --- Items: tables first, then text lines ---
    result.items = _items_from_tables(document) or _items_from_text(text)
    result.notes.append("Heuristic extraction: only unambiguous patterns were filled; everything else is null.")
    return result


_QTY_KEYS = ("qty", "quantity", "units", "nos", "no.")
_NAME_KEYS = ("description", "item", "material", "product", "particular", "goods")
_PRICE_KEYS = ("rate", "price", "unit price", "price/unit", "cost")
_TOTAL_KEYS = ("amount", "total", "value", "line total")
_TAX_KEYS = ("gst", "tax", "vat")
# "UOM" is unambiguous; bare "unit" is not, because "Units" is a quantity column
# and "Price/Unit" is a price column. High-precision keys are tried first.
_UNIT_KEYS_STRONG = ("uom", "units of measure", "unit of measure")
_UNIT_KEYS_WEAK = ("unit",)


def _match_column(
    headers: list[str],
    keys: tuple[str, ...],
    exclude: tuple[str, ...] = (),
    taken: tuple[Optional[int], ...] = (),
) -> Optional[int]:
    taken_set = {t for t in taken if t is not None}
    for index, header in enumerate(headers):
        if index in taken_set:
            continue
        low = str(header).strip().lower()
        if any(x in low for x in exclude):
            continue
        if any(k in low for k in keys):
            return index
    return None


def _items_from_tables(document: ProcessedDocument) -> list:
    from app.schemas.extraction import ExtractedItem, coerce_number

    items: list[ExtractedItem] = []
    for table in document.tables:
        headers = [str(h) for h in table.headers]
        name_i = _match_column(headers, _NAME_KEYS)
        if name_i is None:
            continue
        qty_i = _match_column(headers, _QTY_KEYS, exclude=("price", "rate", "cost"), taken=(name_i,))
        price_i = _match_column(headers, _PRICE_KEYS, taken=(name_i, qty_i))
        total_i = _match_column(headers, _TOTAL_KEYS, taken=(name_i, qty_i, price_i))
        tax_i = _match_column(headers, _TAX_KEYS, taken=(name_i, qty_i, price_i, total_i))
        # Resolve the unit column last, from columns nothing else claimed.
        taken = (name_i, qty_i, price_i, total_i, tax_i)
        unit_i = _match_column(headers, _UNIT_KEYS_STRONG, taken=taken)
        if unit_i is None:
            unit_i = _match_column(
                headers, _UNIT_KEYS_WEAK, exclude=("price", "rate", "cost"), taken=taken
            )

        for row in table.rows:
            if name_i >= len(row):
                continue
            name = row[name_i]
            if name in (None, ""):
                continue
            name_str = str(name).strip()
            # Skip summary rows such as "Sub Total" that sit inside the table.
            if name_str.lower() in {"sub total", "subtotal", "total", "grand total", "net payable"}:
                continue

            def cell(i: Optional[int]):
                return row[i] if i is not None and i < len(row) else None

            attributes = {}
            for idx, header in enumerate(headers):
                if idx in {name_i, qty_i, unit_i, price_i, total_i, tax_i}:
                    continue
                if idx < len(row) and row[idx] not in (None, ""):
                    attributes[str(header)] = row[idx]

            items.append(
                ExtractedItem(
                    original_name=name_str,
                    quantity=coerce_number(cell(qty_i)),
                    unit=str(cell(unit_i)) if cell(unit_i) not in (None, "") else None,
                    unit_price=coerce_number(cell(price_i)),
                    gst_percentage=coerce_number(cell(tax_i)),
                    total_price=coerce_number(cell(total_i)),
                    attributes=attributes,
                )
            )
    return items


_NUMERIC_TOKEN_RE = re.compile(r"^[\d,]+(?:\.\d+)?$")
# Only true unit-of-measure tokens. Dimension words (inch, mm, ft, m) are
# excluded deliberately: they belong to product names such as "PVC Elbow 2 inch"
# and consuming them there corrupts the quantity/rate split.
_UNIT_TOKEN_RE = re.compile(
    r"^(nos?|pcs?|pieces?|btl|bottles?|kgs?|gms?|ltrs?|litres?|box(?:es)?|"
    r"sets?|bags?|rolls?|pkts?|packs?|units?|dozens?|pairs?|coils?|bundles?)$",
    re.IGNORECASE,
)
_SKIP_LINE_KEYS = (
    "sub total", "subtotal", "grand total", "total amount", "net payable", "basic amount",
    "taxable value", "gst @", "transportation", "freight", "carriage", "delivery", "payment",
    "warranty", "authorised", "signatory", "quotation", "date:", "valid",
    # contact / identity lines carry long digit runs that look like columns
    "gstin", "gst no", "phone", "mob:", "mobile", "email", "tel:", "ph:", "contact",
)
# A line whose first word is one of these is a summary row, not a line item.
_SKIP_LINE_PREFIXES = ("total", "sub", "net", "gst", "tax", "amount", "grand", "less", "add")

# Ordered numeric roles declared by an item-table header row.
_HEADER_ROLE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("quantity", ("qty", "quantity", "nos")),
    ("unit_price", ("rate", "price", "cost")),
    ("gst_percentage", ("gst", "tax", "vat")),
    ("total_price", ("amount", "value", "total")),
)


def detect_numeric_columns(text: str) -> Optional[list[str]]:
    """Infer the numeric column order from the item-table header row.

    Reading "Qty | Rate | GST% | Amount" off the header is what lets trailing
    numbers be assigned to fields instead of guessed at.
    """
    best: Optional[list[str]] = None
    best_hits = 0
    for line in text.splitlines():
        low = line.lower()
        if not any(k in low for k in ("qty", "quantity", "rate", "price", "amount")):
            continue
        positions: list[tuple[int, str]] = []
        for role, keys in _HEADER_ROLE_KEYS:
            for key in keys:
                index = low.find(key)
                if index != -1:
                    positions.append((index, role))
                    break
        # De-duplicate roles, keep left-to-right order.
        positions.sort()
        seen: set[str] = set()
        roles = []
        for _, role in positions:
            if role not in seen:
                seen.add(role)
                roles.append(role)
        if len(roles) >= 2 and len(roles) > best_hits:
            best_hits = len(roles)
            best = roles
    return best


def _split_trailing_numbers(tokens: list[str]) -> tuple[list[str], list[float], Optional[str]]:
    """Split a line into (name tokens, trailing numbers, unit token).

    Product names legitimately contain digits ('PVC Pipe 2 inch', 'Class-2, 6m'),
    so the columns are read from the right instead of pattern-matching the name.
    """
    numbers: list[float] = []
    unit: Optional[str] = None
    index = len(tokens)
    while index > 0:
        token = tokens[index - 1]
        if _NUMERIC_TOKEN_RE.match(token):
            value = _num(token)
            if value is None:
                break
            numbers.insert(0, value)
            index -= 1
            continue
        # A unit may sit between the quantity and the rate.
        if unit is None and _UNIT_TOKEN_RE.match(token) and numbers:
            unit = token
            index -= 1
            continue
        break
    return tokens[:index], numbers, unit


def parse_line_item_tokens(line: str, columns: Optional[list[str]] = None):
    """Parse one text line into an ExtractedItem, or None.

    When the document declares its numeric columns in a header row, the trailing
    numbers are mapped onto those columns. When it does not - or when the count
    of numbers does not match the header - the numeric fields are left null and
    the raw numbers are preserved in attributes. Ambiguity produces null, never
    a guess.
    """
    from app.schemas.extraction import ExtractedItem

    tokens = line.split()
    if len(tokens) < 3:
        return None

    # Drop a leading serial number ("1", "1.", "1)").
    if re.match(r"^\d{1,3}[.)]?$", tokens[0]) and len(tokens) > 3:
        tokens = tokens[1:]

    name_tokens, numbers, unit = _split_trailing_numbers(tokens)
    name = " ".join(name_tokens).strip(" .-|:")
    if len(name) < 3 or not any(c.isalpha() for c in name):
        return None
    # A single trailing number is far more often a pin code or a phone fragment
    # than a price column, so it is not enough to call the line an item.
    if len(numbers) < 2:
        return None

    item = ExtractedItem(original_name=name, unit=unit)

    if columns and len(numbers) == len(columns):
        for role, value in zip(columns, numbers):
            setattr(item, role, value)
        # A GST column holding something outside a plausible rate is not GST.
        if item.gst_percentage is not None and not (0 <= item.gst_percentage <= 40):
            item.attributes["_rejected_gst_value"] = item.gst_percentage
            item.gst_percentage = None
        return item

    if len(numbers) == 4:
        qty, rate, gst, amount = numbers
        if 0 <= gst <= 40:
            item.quantity, item.unit_price, item.gst_percentage, item.total_price = qty, rate, gst, amount
            return item
    if len(numbers) == 3:
        item.quantity, item.unit_price, item.total_price = numbers
        return item

    item.attributes["_unparsed_numbers"] = numbers
    item.attributes["_note"] = (
        "Column layout could not be determined for this line; numeric fields left empty "
        "rather than guessed."
    )
    return item


def _items_from_text(text: str) -> list:
    columns = detect_numeric_columns(text)
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) < 8:
            continue
        low = stripped.lower()
        if any(k in low for k in _SKIP_LINE_KEYS):
            continue
        if low.split()[0].strip(":.-") in _SKIP_LINE_PREFIXES:
            continue
        if set(stripped) <= set("-=_ |"):
            continue
        item = parse_line_item_tokens(stripped, columns)
        if item is not None:
            items.append(item)
    return items
