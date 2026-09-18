"""Spend analytics from committed purchase orders (issued, delivered or closed)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

COMMITTED = ("issued", "delivered", "closed")


def spend_summary(pos: list[dict], quotations: list[dict]) -> dict[str, Any]:
    """`pos` are the organization's purchase orders; `quotations` supply the quoted range per request."""
    committed = [p for p in pos if p["status"] in COMMITTED]
    by_supplier: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "orders": 0, "delivered": 0, "on_time": 0})
    by_month: dict[str, float] = defaultdict(float)
    by_item: dict[str, dict] = defaultdict(lambda: {"spend": 0.0, "quantity": 0.0})
    for po in committed:
        total, name = po["pricing"]["total"], po["supplier"].get("name") or "Unknown supplier"
        row = by_supplier[name]
        row["spend"] += total
        row["orders"] += 1
        if po.get("on_time") is not None:
            row["delivered"] += 1
            row["on_time"] += po["on_time"]
        by_month[f"{po['created_at']:%Y-%m}"] += total
        for line in po["lines"]:
            by_item[line["description"]]["spend"] += line["line_total"]
            by_item[line["description"]]["quantity"] += line["quantity"]

    quoted: dict[str, list[float]] = defaultdict(list)
    for q in quotations:
        if q.get("procurement_request_id") and q.get("total_amount"):
            quoted[str(q["procurement_request_id"])].append(q["total_amount"])
    savings = []
    for po in committed:
        quotes = quoted.get(str(po["procurement_request_id"]))
        if quotes and len(quotes) > 1:
            savings.append({"procurement_request_id": po["procurement_request_id"], "po_number": po["po_number"],
                            "highest_quote": max(quotes), "awarded": po["pricing"]["total"],
                            "saving": round(max(quotes) - po["pricing"]["total"], 2)})

    return {
        "currency": committed[0]["pricing"]["currency"] if committed else "INR",
        "total_spend": round(sum(p["pricing"]["total"] for p in committed), 2),
        "orders": len(committed),
        "by_supplier": sorted(
            ({"supplier": k, **{f: round(v, 2) for f, v in r.items()},
              "on_time_rate": round(r["on_time"] / r["delivered"], 4) if r["delivered"] else None}
             for k, r in by_supplier.items()), key=lambda r: -r["spend"]),
        "by_month": [{"month": m, "spend": round(v, 2)} for m, v in sorted(by_month.items())],
        "by_item": sorted(({"item": k, **{f: round(v, 2) for f, v in r.items()}} for k, r in by_item.items()),
                          key=lambda r: -r["spend"]),
        "savings": savings,
    }
