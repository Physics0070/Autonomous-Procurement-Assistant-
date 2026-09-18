"""Purchase orders: award from a comparison, GST split, lifecycle, delivery, PDF."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.errors import ConflictError
from app.core.gstin import state_code
from app.services.automation.communications import history_entry, now

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


def build_purchase_order(request: dict, quotation: dict, supplier: Optional[dict], buyer: dict) -> dict[str, Any]:
    """PO draft from the quotation's effective data. Lines are requested quantity x quoted price;
    unmatched request items are warned about, never guessed."""
    data = quotation.get("effective_data") or quotation.get("normalized_data") or {}
    pricing = data.get("pricing") or {}
    quoted = {i.get("line_id"): i for i in data.get("items") or []}
    matches = {m["request_item_id"]: m for m in (quotation.get("match_result") or {}).get("matches") or []}

    lines, warnings, taxable = [], [], {}
    for item in request.get("items") or []:
        match = matches.get(item["item_id"])
        line = quoted.get(match.get("quotation_line_id")) if match and match.get("matched") else None
        price = (match or {}).get("unit_price") or (line or {}).get("unit_price")
        if not line or price is None or item.get("quantity") is None:
            warnings.append(f"'{item['name']}' has no matched, priced line in this quotation and is not on the PO.")
            continue
        rate = line.get("tax_percentage") if line.get("tax_percentage") is not None else pricing.get("tax_percentage") or 0
        total = round(item["quantity"] * price, 2)
        taxable[rate] = taxable.get(rate, 0) + total
        lines.append({
            "request_item_id": item["item_id"], "description": item["name"], "quantity": item["quantity"],
            "unit": item.get("unit"), "unit_price": price, "tax_percentage": rate, "line_total": total,
        })

    supplier_block = {**(data.get("supplier") or {}), **{k: v for k, v in (supplier or {}).items() if v}}
    subtotal = round(sum(line["line_total"] for line in lines), 2)
    taxes = tax_split(taxable, buyer.get("gst_number"), supplier_block.get("gst_number"))
    freight = pricing.get("transportation_cost") or 0
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
            "subtotal": subtotal, "taxes": taxes, "freight": freight,
            "total": round(subtotal + sum(t["amount"] for t in taxes) + freight, 2),
        },
        "terms": {
            "delivery_days": (data.get("delivery") or {}).get("delivery_days"),
            "payment_terms": (data.get("payment_terms") or {}).get("raw_terms"),
        },
        "status": "draft",
    }


def transition(po: dict, action: str, user_id: str, delivered_at: Optional[datetime] = None) -> dict[str, Any]:
    allowed, target = TRANSITIONS[action]
    if po["status"] not in allowed:
        raise ConflictError(f"Cannot {action} a purchase order that is {po['status']}.")
    fields: dict[str, Any] = {"status": target}
    if action == "issue":
        fields["issued_at"] = now()
        days = (po.get("terms") or {}).get("delivery_days")
        if days is not None:
            fields["expected_delivery_date"] = now() + timedelta(days=days)
    if action == "deliver":
        fields.update(record_delivery(po.get("expected_delivery_date"), delivered_at or now()))
    return {"$set": fields, "$push": {"history": history_entry(action, user_id)}}


def record_delivery(expected: Optional[datetime], delivered_at: datetime) -> dict[str, Any]:
    """The real delivery history the reliability model learns from."""
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=timezone.utc)
    if expected is None:
        return {"delivered_at": delivered_at, "on_time": None, "delay_days": None}
    delay = (delivered_at.date() - expected.date()).days
    return {"delivered_at": delivered_at, "on_time": delay <= 0, "delay_days": max(delay, 0)}


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
