"""Purchase orders: award from a comparison, GST split, lifecycle, delivery, PDF."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.errors import ConflictError
from app.core.gstin import state_code
from app.services.automation.communications import history_entry, now
from app.services.procurement.validation import parse_date

# action -> (statuses it is allowed from, resulting status)
TRANSITIONS = {
    "approve": ({"draft"}, "approved"),
    "issue": ({"approved"}, "issued"),
    "deliver": ({"issued"}, "delivered"),
    "close": ({"delivered"}, "closed"),
    "cancel": ({"draft", "approved", "issued"}, "cancelled"),
}


def tax_split(taxable_by_rate: dict[float, float], buyer_gstin: Optional[str], supplier_gstin: Optional[str]) -> list[dict]:
    """CGST+SGST within a state, IGST across states, plain GST when a GSTIN is unknown."""
    buyer, supplier = state_code(buyer_gstin), state_code(supplier_gstin)
    lines = []
    for rate, taxable in sorted(taxable_by_rate.items()):
        tax = round(taxable * rate / 100, 2)
        if not rate:
            continue
        if buyer and supplier and buyer == supplier:
            lines += [{"name": "CGST", "rate": rate / 2, "amount": round(tax / 2, 2)},
                      {"name": "SGST", "rate": rate / 2, "amount": round(tax - round(tax / 2, 2), 2)}]
        else:
            lines.append({"name": "IGST" if buyer and supplier else "GST", "rate": rate, "amount": tax})
    return lines


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_purchase_order(request: dict, quotation: dict, supplier: Optional[dict], buyer: dict) -> dict[str, Any]:
    """PO draft from the quotation's effective data. Lines are requested quantity x quoted price; unmatched request
    items are warned about, never guessed.

    GST: if the quotation says its rates include GST (and its total does not add GST on top of the lines), GST is
    taken out of each unit price so it is not charged twice; if it is unclear whether prices include GST, the PO says
    so. Discounts: a percentage discount applies to the PO subtotal whatever the quantities; a fixed amount applies
    only when the PO orders exactly what was quoted, and otherwise is left off with a warning (it was offered for
    that order). A quantity different from the quoted one is flagged, since rates are often tiered by quantity.
    Prices or quantities that are missing, zero, negative or not finite never reach a PO line.
    """
    from app.services.procurement.comparison import _close, gst_wording

    data = quotation.get("effective_data") or quotation.get("normalized_data") or {}
    pricing = data.get("pricing") or {}
    quoted = {i.get("line_id"): i for i in data.get("items") or []}
    matches = {m["request_item_id"]: m for m in (quotation.get("match_result") or {}).get("matches") or []}

    gross, printed = _finite(pricing.get("subtotal")), _finite(pricing.get("total_amount"))
    quoted_freight = _finite(pricing.get("transportation_cost")) or 0.0
    net = gross - (_finite(pricing.get("discount_amount")) or 0.0) if gross is not None else None
    wording = gst_wording((quotation.get("raw_content") or {}).get("raw_text"))
    tax_on_top = (_finite(pricing.get("tax_amount")) or 0) > 0 or (
        printed is not None and net is not None and not any(_close(printed, net + f) for f in {quoted_freight, 0.0}))
    prices_include_gst = wording == "inclusive" and not tax_on_top
    gst_stated = pricing.get("tax_percentage") is not None or pricing.get("tax_amount") is not None or any(
        i.get("tax_percentage") is not None for i in quoted.values())

    lines, warnings, used = [], [], {}
    for item in request.get("items") or []:
        match = matches.get(item["item_id"])
        line = quoted.get(match.get("quotation_line_id")) if match and match.get("matched") else None
        price = (match or {}).get("unit_price") or (line or {}).get("unit_price")
        if not line or price is None or item.get("quantity") is None:
            warnings.append(f"'{item['name']}' has no matched, priced line in this quotation and is not on the PO.")
            continue
        price, quantity = _finite(price), _finite(item["quantity"])
        rate = line.get("tax_percentage") if line.get("tax_percentage") is not None else pricing.get("tax_percentage") or 0
        rate = _finite(rate)
        if price is None or price <= 0 or quantity is None or quantity <= 0 or rate is None or not 0 <= rate <= 100:
            warnings.append(f"'{item['name']}' has an invalid price, quantity or GST rate in the quotation and is not on the PO.")
            continue
        quoted_quantity = _finite(line.get("quantity"))
        if quoted_quantity and quoted_quantity != quantity:
            warnings.append(f"'{item['name']}' was quoted for {quoted_quantity:g}; ordering {quantity:g}. Confirm the rate "
                            "applies at this quantity (rates are often tiered).")
        if prices_include_gst and rate:
            # Rate x quantity includes GST: the taxable value is that amount less GST.
            total = round(round(quantity * price, 2) / (1 + rate / 100), 2)
            unit_price = round(total / quantity, 4)
        else:
            total, unit_price = round(quantity * price, 2), price
        used[match.get("quotation_line_id")] = quantity
        lines.append({
            "request_item_id": item["item_id"], "description": item["name"], "quantity": quantity,
            "unit": item.get("unit"), "unit_price": unit_price, "tax_percentage": rate, "line_total": total,
            **({"quoted_unit_price": price} if prices_include_gst and rate else {}),
        })
    if prices_include_gst and lines:
        warnings.append("The quotation's rates are inclusive of GST, so GST has been taken out of the unit prices "
                        "and added back once below.")
    elif not gst_stated and wording is None and lines:
        warnings.append("The quotation does not show whether its prices include GST; confirm before approving.")

    supplier_block = {**(data.get("supplier") or {}), **{k: v for k, v in (supplier or {}).items() if v}}
    subtotal = round(sum(line["line_total"] for line in lines), 2)
    percent, fixed = _finite(pricing.get("discount_percentage")), _finite(pricing.get("discount_amount"))
    discount, discount_type = 0.0, None
    if percent is not None and 0 < percent <= 100:
        discount_type = "percentage"
        discount = round(subtotal * percent / 100, 2)
    elif fixed is not None and fixed > 0:
        discount_type = "fixed"
        quoted_quantities = {lid: _finite(i.get("quantity")) for lid, i in quoted.items()}
        if used == quoted_quantities:
            discount = round(min(fixed, subtotal), 2)
        else:
            warnings.append(f"A fixed discount of {fixed:,.2f} was quoted for the quoted items and quantities; this "
                            "order differs, so it is not applied. Agree the discount with the supplier.")
    # A discount on the invoice reduces the taxable value, so it is shared out before GST.
    share = discount / subtotal if subtotal else 0.0
    taxable: dict[float, float] = {}
    for line in lines:
        taxable[line["tax_percentage"]] = taxable.get(line["tax_percentage"], 0.0) + line["line_total"] * (1 - share)
    taxes = tax_split(taxable, buyer.get("gst_number"), supplier_block.get("gst_number"))
    freight = round(quoted_freight, 2) if quoted_freight >= 0 else 0.0
    return {
        "procurement_request_id": request["id"],
        "quotation_id": quotation["id"],
        "supplier_id": quotation.get("supplier_id") or (supplier or {}).get("id"),
        "supplier": {k: supplier_block.get(k) for k in ("name", "email", "phone", "gst_number", "address")},
        "buyer": {k: buyer.get(k) for k in ("name", "address", "gst_number", "state", "contact_email", "contact_phone")},
        "lines": lines,
        "warnings": warnings,
        "pricing": {
            "currency": pricing.get("currency") or request.get("currency") or "INR",
            "subtotal": subtotal, "discount": discount, "discount_type": discount_type, "taxes": taxes,
            "freight": freight,
            "total": round(subtotal - discount + sum(t["amount"] for t in taxes) + freight, 2),
        },
        "terms": {
            "delivery_days": (data.get("delivery") or {}).get("delivery_days"),
            "delivery_date": (data.get("delivery") or {}).get("delivery_date"),
            "payment_terms": (data.get("payment_terms") or {}).get("raw_terms"),
        },
        "status": "draft",
    }


def reconcile(po: dict) -> list[str]:
    """Every way the PO's figures can fail to add up, to the paisa. Empty when it is sound."""
    pricing = po.get("pricing") or {}
    lines = po.get("lines") or []
    problems = []
    money = {"subtotal": pricing.get("subtotal"), "discount": pricing.get("discount") or 0,
             "freight": pricing.get("freight") or 0, "total": pricing.get("total")}
    money.update({f"{t.get('name')} {t.get('rate')}%": t.get("amount") for t in pricing.get("taxes") or []})
    for n, line in enumerate(lines, 1):
        money.update({f"line {n} quantity": line.get("quantity"), f"line {n} unit price": line.get("unit_price"),
                      f"line {n} amount": line.get("line_total")})
    bad = [name for name, value in money.items() if _finite(value) is None or _finite(value) < 0]
    if bad:
        return [f"Invalid or negative value: {', '.join(bad)}."]
    if not lines:
        problems.append("The order has no lines.")
    cents = lambda value: round(float(value) * 100)  # noqa: E731
    if sum(cents(line["line_total"]) for line in lines) != cents(pricing["subtotal"]):
        problems.append("The line amounts do not add up to the subtotal.")
    for n, line in enumerate(lines, 1):
        if abs(line["quantity"] * line["unit_price"] - line["line_total"]) > 0.01 + line["quantity"] * 0.00005:
            problems.append(f"Line {n}: quantity x unit price does not equal its amount.")
    if cents(money["discount"]) > cents(pricing["subtotal"]):
        problems.append("The discount is larger than the subtotal.")
    expected = (cents(pricing["subtotal"]) - cents(money["discount"]) + sum(cents(t["amount"]) for t in pricing.get("taxes") or [])
                + cents(money["freight"]))
    if expected != cents(pricing["total"]):
        problems.append("The total is not subtotal - discount + GST + freight.")
    if cents(pricing["total"]) <= 0:
        problems.append("The total is not above zero.")
    return problems


def transition(po: dict, action: str, user_id: str, delivered_at: Optional[datetime] = None,
               cancelled_by: Optional[str] = None, cancel_reason: Optional[str] = None) -> dict[str, Any]:
    allowed, target = TRANSITIONS[action]
    if po["status"] not in allowed:
        raise ConflictError(f"Cannot {action} a purchase order that is {po['status']}.")
    fields: dict[str, Any] = {"status": target}
    if action == "approve":
        problems = reconcile(po)
        if problems:
            raise ConflictError("This purchase order cannot be approved: " + " ".join(problems), {"problems": problems})
    if action == "issue":
        fields["issued_at"] = now()
        terms = po.get("terms") or {}
        # A date the supplier actually committed to beats a lead time counted from today.
        promised = parse_date(terms.get("delivery_date"))
        if promised is not None:
            fields["expected_delivery_date"] = promised.replace(tzinfo=timezone.utc)
        elif terms.get("delivery_days") is not None:
            fields["expected_delivery_date"] = now() + timedelta(days=terms["delivery_days"])
    if action == "deliver":
        fields.update(record_delivery(po.get("expected_delivery_date"), delivered_at or now()))
    if action == "cancel":
        # Only a cancellation the supplier caused counts against it in the scorecard.
        fields.update({"cancelled_at": now(), "cancelled_by": cancelled_by, "cancel_reason": cancel_reason})
        # A cancelled order no longer holds the request's award, so the request can be awarded again.
        return {"$set": fields, "$unset": {"award_key": ""}, "$push": {"history": history_entry(action, user_id)}}
    return {"$set": fields, "$push": {"history": history_entry(action, user_id)}}


def record_delivery(expected: Optional[datetime], delivered_at: datetime) -> dict[str, Any]:
    """The real delivery history the reliability model learns from."""
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=timezone.utc)
    if expected is None:
        return {"delivered_at": delivered_at, "on_time": None, "delay_days": None}
    delay = (delivered_at.date() - expected.date()).days
    return {"delivered_at": delivered_at, "on_time": delay <= 0, "delay_days": max(delay, 0)}


def record_receipt(po: dict, lines: list[dict], invoice: dict[str, Any], user_id: str) -> dict[str, Any]:
    """What arrived per PO line (by its index) and what was invoiced: the in-full, quality and commercial evidence.

    Every PO line must appear exactly once; accepted = received - rejected, and in-full means accepted covers the
    ordered quantity on every line. Quantities are already finite and non-negative (checked by the API model).
    """
    from app.services.procurement.reliability import delivered_in_full

    if po["status"] not in ("delivered", "closed"):
        raise ConflictError("A receipt can only be recorded for a delivered purchase order.")
    po_lines = po.get("lines") or []
    indexes = [line["line"] for line in lines]
    if sorted(indexes) != list(range(len(po_lines))):
        raise ConflictError(f"Give received and rejected quantities for each of the {len(po_lines)} lines of the "
                            f"order exactly once (lines 0 to {len(po_lines) - 1}).")
    for line in lines:
        rejected = line.get("rejected_quantity")
        if rejected is not None and rejected > line["received_quantity"]:
            raise ConflictError(f"Line {line['line'] + 1}: more rejected than received.")
    # No rejected quantity means quality has not been inspected yet: recorded as such, never as zero rejected.
    stored = []
    for line in sorted(lines, key=lambda line: line["line"]):
        rejected = line.get("rejected_quantity")
        stored.append({"line": line["line"], "received_quantity": line["received_quantity"],
                       "rejected_quantity": rejected, "inspected": rejected is not None,
                       "accepted_quantity": line["received_quantity"] - rejected if rejected is not None else None})
    triples = [(float(po_line["quantity"]), r["received_quantity"], r["rejected_quantity"]) for po_line, r in zip(po_lines, stored)]
    receipt = {"lines": stored, "in_full": delivered_in_full(triples),
               "inspected": all(r["inspected"] for r in stored), **invoice,
               "recorded_by": user_id, "recorded_at": now()}
    return {"$set": {"receipt": receipt}, "$push": {"history": history_entry("receipt_recorded", user_id)}}


def combine(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """One update document from two, so a delivery and its receipt are written together or not at all."""
    out: dict[str, Any] = {"$set": {**first.get("$set", {}), **second.get("$set", {})}}
    history = [*(u["$push"]["history"] for u in (first, second) if "history" in u.get("$push", {}))]
    if history:
        out["$push"] = {"history": {"$each": history}}
    for op in ("$unset",):
        if first.get(op) or second.get(op):
            out[op] = {**first.get(op, {}), **second.get(op, {})}
    return out


def render_po_pdf(po: dict) -> bytes:
    """Plain A4 PDF. Amounts use the currency code, not a symbol, so the base font suffices."""
    import fitz  # PyMuPDF

    cur = po["pricing"]["currency"]
    buyer, supplier = po["buyer"], po["supplier"]
    text = [
        f"PURCHASE ORDER {po['po_number']}", f"Status: {po['status']}", "",
        f"Buyer: {buyer.get('name') or ''}", f"  {buyer.get('address') or ''}", f"  GSTIN: {buyer.get('gst_number') or '-'}",
        f"Supplier: {supplier.get('name') or ''}", f"  {supplier.get('address') or ''}", f"  GSTIN: {supplier.get('gst_number') or '-'}",
        "", f"{'#':<3}{'Item':<40}{'Qty':>10}{'Rate':>14}{'Tax%':>6}{'Amount':>16}",
    ]
    for n, line in enumerate(po["lines"], 1):
        text.append(f"{n:<3}{line['description'][:39]:<40}{line['quantity']:>10g}{line['unit_price']:>14,.2f}"
                    f"{line['tax_percentage']:>6g}{line['line_total']:>16,.2f}")
    text += ["", f"Subtotal: {cur} {po['pricing']['subtotal']:,.2f}"]
    if po["pricing"].get("discount"):
        text += [f"Less discount: {cur} {po['pricing']['discount']:,.2f}"]
    text += [f"{t['name']} {t['rate']:g}%: {cur} {t['amount']:,.2f}" for t in po["pricing"]["taxes"]]
    text += [f"Freight: {cur} {po['pricing']['freight']:,.2f}", f"TOTAL: {cur} {po['pricing']['total']:,.2f}", "",
             f"Delivery: {po['terms'].get('delivery_days') or '-'} days   Payment: {po['terms'].get('payment_terms') or '-'}"]

    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    y = 50
    for row in text:
        if y > 800:
            page, y = pdf.new_page(width=595, height=842), 50
        page.insert_text((40, y), row, fontname="cour", fontsize=9)
        y += 13
    return pdf.tobytes()
