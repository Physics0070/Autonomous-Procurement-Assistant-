"""A fresh procurement round on the `sourcing` fixture's data.

One procurement request holds at most one live purchase order, so tests that need several orders for the same
supplier (scorecard history, analytics) open a new request with the same items and the same two quotations, and run
its comparison, for each order.
"""
import copy

from bson import ObjectId


async def new_round(api, s: dict) -> dict:
    from app.core.database import get_database
    from app.repositories.quotations import QuotationRepository

    h = s["headers"]
    items = [{k: item[k] for k in ("name", "quantity", "unit", "specifications") if item.get(k) is not None}
             for item in s["request"]["items"]]
    created = await api.post("/api/v1/procurement-requests", headers=h, json={"title": s["request"]["title"], "items": items})
    assert created.status_code == 201, created.text
    request = created.json()
    item_ids = dict(zip((i["item_id"] for i in s["request"]["items"]), (i["item_id"] for i in request["items"])))

    repo, out = QuotationRepository(get_database()), {**s, "request": request}
    for key in ("q_shree", "q_apex"):
        quotation = {k: v for k, v in copy.deepcopy(s[key]).items() if k not in ("id", "organization_id", "created_at", "updated_at")}
        quotation["procurement_request_id"] = ObjectId(request["id"])
        quotation["supplier_id"] = ObjectId(quotation["supplier_id"])
        for match in (quotation.get("match_result") or {}).get("matches") or []:
            match["request_item_id"] = item_ids[match["request_item_id"]]
        out[key] = await repo.create(s[key]["organization_id"], quotation)
    compared = await api.post(f"/api/v1/comparisons/procurement-requests/{request['id']}", headers=h,
                              json={"include_ai_explanation": False})
    assert compared.status_code == 200, compared.text
    out["comparison"] = compared.json()
    return out
