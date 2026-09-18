"""End-to-end test of the whole system through the HTTP API.

Covers: auth, org isolation, procurement CRUD, suppliers, upload, the full
extraction -> normalization -> matching pipeline, corrections, comparison and
the dashboard. Run with the backend already listening on BASE_URL.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")
API = f"{BASE}/api/v1"
SAMPLES = Path(__file__).resolve().parents[1] / "samples"

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    if condition:
        PASSED.append(name)
        print(f"  [PASS] {name}")
    else:
        FAILED.append(f"{name} :: {detail}")
        print(f"  [FAIL] {name} :: {detail}")
    return condition


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> int:
    client = httpx.Client(timeout=120.0)
    suffix = uuid.uuid4().hex[:8]

    # ------------------------------------------------------------------
    section("1. HEALTH & CAPABILITIES")
    # ------------------------------------------------------------------
    health = client.get(f"{BASE}/health").json()
    check("health endpoint responds", health.get("status") in ("ok", "degraded"), str(health))
    check("mongodb connected", health["database"]["connected"] is True, str(health["database"]))
    ai_configured = health["ai"]["configured"]
    ocr_available = health["ocr"]["available"]
    print(f"  ..  AI configured: {ai_configured} | OCR: {health['ocr']['engine']}")

    # ------------------------------------------------------------------
    section("2. AUTHENTICATION")
    # ------------------------------------------------------------------
    reg = client.post(
        f"{API}/auth/register",
        json={
            "name": "Asha Patil",
            "email": f"asha+{suffix}@acme-eng-demo.com",
            "password": "StrongPassw0rd!",
            "organization_name": f"Acme Engineering {suffix}",
            "industry": "Manufacturing",
        },
    )
    check("register returns 201", reg.status_code == 201, f"{reg.status_code} {reg.text[:200]}")
    reg_data = reg.json()
    token_a = reg_data["access_token"]
    org_a_id = reg_data["organization"]["id"]
    check("register returns a token", bool(token_a))
    check("first user is admin", reg_data["user"]["role"] == "admin", reg_data["user"]["role"])

    dup = client.post(
        f"{API}/auth/register",
        json={
            "name": "Dup", "email": f"asha+{suffix}@acme-eng-demo.com", "password": "StrongPassw0rd!",
            "organization_name": "Dup Org",
        },
    )
    check("duplicate email rejected (409)", dup.status_code == 409, str(dup.status_code))

    login = client.post(
        f"{API}/auth/login",
        json={"email": f"asha+{suffix}@acme-eng-demo.com", "password": "StrongPassw0rd!"},
    )
    check("login returns 200", login.status_code == 200, f"{login.status_code} {login.text[:200]}")
    token_a = login.json()["access_token"]

    bad = client.post(
        f"{API}/auth/login",
        json={"email": f"asha+{suffix}@acme-eng-demo.com", "password": "WrongPassword!"},
    )
    check("wrong password rejected (401)", bad.status_code == 401, str(bad.status_code))

    auth_a = {"Authorization": f"Bearer {token_a}"}
    me = client.get(f"{API}/auth/me", headers=auth_a)
    check("auth/me returns 200", me.status_code == 200, str(me.status_code))
    check("auth/me returns the right org", me.json()["organization"]["id"] == org_a_id)

    no_token = client.get(f"{API}/auth/me")
    check("protected route without token -> 401", no_token.status_code == 401, str(no_token.status_code))
    bad_token = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not.a.real.token"})
    check("protected route with bad token -> 401", bad_token.status_code == 401, str(bad_token.status_code))

    # ------------------------------------------------------------------
    section("3. PROCUREMENT REQUEST CRUD")
    # ------------------------------------------------------------------
    created = client.post(
        f"{API}/procurement-requests",
        headers=auth_a,
        json={
            "title": "Plumbing materials for Unit 2 expansion",
            "description": "Need 100 units of 2-inch PVC pipe plus fittings.",
            "department": "Maintenance",
            "currency": "INR",
            "status": "open",
            "items": [
                {"name": "PVC Pipe, 2 inch", "quantity": 100, "unit": "Nos",
                 "specifications": "Class-2, 6 metre lengths"},
                {"name": "PVC Elbow 2 inch", "quantity": 40, "unit": "Nos"},
                {"name": "Solvent Cement 500 ml", "quantity": 10, "unit": "Bottle"},
            ],
        },
    )
    check("create request 201", created.status_code == 201, f"{created.status_code} {created.text[:300]}")
    request_id = created.json()["id"]
    items = created.json()["items"]
    check("request items normalized", all(i.get("normalized_name") for i in items),
          str([i.get("normalized_name") for i in items]))
    print(f"  ..  normalized: {[i['normalized_name'] for i in items]}")

    listed = client.get(f"{API}/procurement-requests", headers=auth_a)
    check("list requests 200", listed.status_code == 200)
    check("created request appears in list",
          any(r["id"] == request_id for r in listed.json()["items"]))

    fetched = client.get(f"{API}/procurement-requests/{request_id}", headers=auth_a)
    check("get request 200", fetched.status_code == 200)

    updated = client.put(
        f"{API}/procurement-requests/{request_id}",
        headers=auth_a,
        json={"department": "Projects", "status": "comparing"},
    )
    check("update request 200", updated.status_code == 200, updated.text[:200])
    check("update applied", updated.json()["department"] == "Projects", updated.json().get("department"))

    throwaway = client.post(
        f"{API}/procurement-requests", headers=auth_a,
        json={"title": "Throwaway", "items": []},
    ).json()["id"]
    deleted = client.delete(f"{API}/procurement-requests/{throwaway}", headers=auth_a)
    check("delete request 204", deleted.status_code == 204, str(deleted.status_code))
    gone = client.get(f"{API}/procurement-requests/{throwaway}", headers=auth_a)
    check("deleted request is gone (404)", gone.status_code == 404, str(gone.status_code))

    # ------------------------------------------------------------------
    section("4. SUPPLIERS")
    # ------------------------------------------------------------------
    supplier = client.post(
        f"{API}/suppliers", headers=auth_a,
        json={
            "name": "Shree Plastics & Pipes Pvt Ltd",
            "email": "sales@shreeplastics.co.in",
            "phone": "+91 98220 41556",
            "gst_number": "27AABCS1429B1ZQ",
            "address": "Plot 42, MIDC Industrial Area, Pune - 411018",
        },
    )
    check("create supplier 201", supplier.status_code == 201, supplier.text[:250])
    supplier_id = supplier.json()["id"]
    check("supplier has reliability score",
          supplier.json()["reliability"]["score"] is not None)
    check("reliability is rule-based, not ML",
          supplier.json()["reliability"]["method"] == "rule_based")

    partial = client.post(f"{API}/suppliers", headers=auth_a, json={"name": f"Incomplete Traders {suffix}"})
    check("supplier with only a name is accepted", partial.status_code == 201, partial.text[:200])

    dupe = client.post(f"{API}/suppliers", headers=auth_a, json={"name": "Shree Plastics & Pipes Pvt Ltd"})
    check("duplicate supplier rejected (409)", dupe.status_code == 409, str(dupe.status_code))

    got = client.get(f"{API}/suppliers/{supplier_id}", headers=auth_a)
    check("get supplier 200", got.status_code == 200)
    check("supplier list 200", client.get(f"{API}/suppliers", headers=auth_a).status_code == 200)

    # ------------------------------------------------------------------
    section("5. DOCUMENT UPLOAD (all formats)")
    # ------------------------------------------------------------------
    files = sorted(SAMPLES.glob("*"))
    check("sample documents exist", len(files) >= 5, f"found {len(files)}")
    quotation_ids: list[str] = []
    for path in files:
        with path.open("rb") as handle:
            response = client.post(
                f"{API}/documents/upload",
                headers=auth_a,
                files={"file": (path.name, handle, _mime(path))},
                data={"procurement_request_id": request_id},
            )
        ok = check(f"upload {path.name}", response.status_code == 201,
                   f"{response.status_code} {response.text[:200]}")
        if ok:
            body = response.json()
            quotation_ids.append(body["quotation_id"])
            check(f"  {path.name} queued", body["processing_status"] in ("QUEUED", "UPLOADED"),
                  body["processing_status"])

    rejected = client.post(
        f"{API}/documents/upload", headers=auth_a,
        files={"file": ("notes.exe", b"MZ\x00\x00binary", "application/octet-stream")},
    )
    check("unsupported file type rejected", rejected.status_code in (400, 422), str(rejected.status_code))

    # ------------------------------------------------------------------
    section("6. BACKGROUND PROCESSING")
    # ------------------------------------------------------------------
    print("  ..  waiting for the queue to drain")
    terminal = {"COMPLETED", "REQUIRES_REVIEW", "FAILED"}
    deadline = time.time() + 180
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = {}
        for qid in quotation_ids:
            row = client.get(f"{API}/quotations/{qid}", headers=auth_a).json()
            statuses[qid] = row.get("processing_status")
        if all(s in terminal for s in statuses.values()):
            break
        time.sleep(3)
    print(f"  ..  final statuses: {sorted(set(statuses.values()))}")
    check("all quotations reached a terminal state",
          all(s in terminal for s in statuses.values()), str(statuses))
    check("no quotation FAILED",
          not any(s == "FAILED" for s in statuses.values()), str(statuses))

    # ------------------------------------------------------------------
    section("7. PIPELINE OUTPUT PER QUOTATION")
    # ------------------------------------------------------------------
    detail_by_id = {}
    for qid in quotation_ids:
        detail = client.get(f"{API}/quotations/{qid}", headers=auth_a).json()
        detail_by_id[qid] = detail
        name = (detail.get("source") or {}).get("original_filename")
        raw = detail.get("raw_content") or {}
        ai = detail.get("ai_extraction") or {}
        norm = detail.get("normalized_data") or {}
        validation = detail.get("validation") or {}
        match = detail.get("match_result") or {}
        print(f"\n  --- {name} [{detail.get('processing_status')}] ---")
        print(f"      raw: type={raw.get('document_type')} chars={len(raw.get('raw_text') or '')} "
              f"tables={len(raw.get('tables') or [])} ocr={raw.get('ocr_used')} ({raw.get('ocr_engine')})")
        print(f"      ai: provider={ai.get('provider')} items={len(ai.get('items') or [])}")
        print(f"      normalized: items={len(norm.get('items') or [])} "
              f"total={(norm.get('pricing') or {}).get('landed_total')} "
              f"delivery={(norm.get('delivery') or {}).get('delivery_days')}d")
        print(f"      validation: errors={validation.get('error_count')} warnings={validation.get('warning_count')}")
        print(f"      matching: matched={match.get('matched_count')} review={match.get('review_count')} "
              f"unmatched={match.get('unmatched_count')} coverage={match.get('coverage')}")
        print(f"      supplier: {detail.get('supplier_name')}")

        check(f"{name}: raw_content preserved", bool(raw.get("raw_text") or raw.get("tables")))
        check(f"{name}: ai_extraction stored", bool(ai))
        check(f"{name}: validation report stored", "issues" in validation)
        check(f"{name}: normalized_data stored", bool(norm.get("items") is not None))
        check(f"{name}: confidence recorded", (detail.get("confidence") or {}).get("overall") is not None)
        check(f"{name}: processing history recorded", len(detail.get("processing_history") or []) >= 3)

    ocr_used_any = any(
        (d.get("raw_content") or {}).get("ocr_used") for d in detail_by_id.values()
    )
    check("OCR ran for scanned/image inputs", ocr_used_any or not ocr_available)

    digital = [
        d for d in detail_by_id.values()
        if (d.get("raw_content") or {}).get("document_type") == "pdf_digital"
    ]
    check("OCR skipped for digital PDFs",
          all(not (d.get("raw_content") or {}).get("ocr_used") for d in digital),
          "a digital PDF was unnecessarily OCR'd")

    excel = [
        d for d in detail_by_id.values()
        if (d.get("raw_content") or {}).get("document_type") == "excel"
    ]
    check("Excel produced tables", bool(excel) and len(excel[0]["raw_content"]["tables"]) > 0)

    matched_any = any(
        (d.get("match_result") or {}).get("matched_count", 0) > 0 for d in detail_by_id.values()
    )
    check("product matching produced matches", matched_any)

    # ------------------------------------------------------------------
    section("8. ORIGINAL FILE PRESERVED OUTSIDE MONGODB")
    # ------------------------------------------------------------------
    first_id = quotation_ids[0]
    original = client.get(f"{API}/quotations/{first_id}/file", headers=auth_a)
    check("original file downloadable", original.status_code == 200, str(original.status_code))
    check("original file has content", len(original.content) > 100, f"{len(original.content)} bytes")
    source = detail_by_id[first_id]["source"]
    check("storage_key recorded, not file bytes", bool(source.get("storage_key")))

    # ------------------------------------------------------------------
    section("9. USER CORRECTIONS (must not overwrite raw or AI data)")
    # ------------------------------------------------------------------
    target_id = None
    for qid, detail in detail_by_id.items():
        if (detail.get("normalized_data") or {}).get("items"):
            target_id = qid
            break
    if check("a quotation with items is available to correct", target_id is not None):
        before = detail_by_id[target_id]
        original_ai_items = (before.get("ai_extraction") or {}).get("items") or []
        original_norm_items = (before.get("normalized_data") or {}).get("items") or []
        original_first_price = original_norm_items[0].get("unit_price")

        corrected = client.post(
            f"{API}/quotations/{target_id}/corrections",
            headers=auth_a,
            json={
                "corrections": {"items.0.unit_price": 999.5, "delivery.delivery_days": 3},
                "note": "Confirmed by phone with the supplier.",
            },
        )
        check("corrections accepted", corrected.status_code == 200, corrected.text[:300])
        after = corrected.json()

        check("effective_data reflects the correction",
              (after.get("effective_data") or {}).get("items", [{}])[0].get("unit_price") == 999.5,
              str((after.get("effective_data") or {}).get("items", [{}])[0].get("unit_price")))
        check("effective delivery reflects the correction",
              (after.get("effective_data") or {}).get("delivery", {}).get("delivery_days") == 3)
        check("normalized_data was NOT overwritten",
              (after.get("normalized_data") or {}).get("items", [{}])[0].get("unit_price") == original_first_price,
              "normalized_data changed")
        check("ai_extraction was NOT overwritten",
              ((after.get("ai_extraction") or {}).get("items") or []) == original_ai_items,
              "ai_extraction changed")
        check("raw_content was NOT overwritten",
              (after.get("raw_content") or {}).get("raw_text")
              == (before.get("raw_content") or {}).get("raw_text"),
              "raw_content changed")
        check("correction history recorded with previous value",
              len(after.get("user_corrections") or []) >= 2
              and after["user_corrections"][0].get("previous_value") == original_first_price,
              str(after.get("user_corrections"))[:300])

        bad_path = client.post(
            f"{API}/quotations/{target_id}/corrections",
            headers=auth_a, json={"corrections": {"nonexistent.path.here": 1}},
        )
        check("unknown correction path rejected", bad_path.status_code == 422, str(bad_path.status_code))

    # ------------------------------------------------------------------
    section("10. SUPPLIER COMPARISON")
    # ------------------------------------------------------------------
    weights = client.get(f"{API}/comparisons/weights", headers=auth_a).json()
    check("weights endpoint returns config", "weights" in weights, str(weights))
    print(f"  ..  weights: {weights['weights']}")

    comparison = client.post(
        f"{API}/comparisons/procurement-requests/{request_id}",
        headers=auth_a, json={"include_ai_explanation": True},
    )
    check("comparison computed", comparison.status_code == 200, comparison.text[:400])
    result = comparison.json()
    suppliers_scored = result.get("suppliers") or []
    check("comparison scored at least 2 suppliers", len(suppliers_scored) >= 2, str(len(suppliers_scored)))
    check("comparison is deterministic scoring",
          result.get("method") == "deterministic_weighted_scoring", str(result.get("method")))
    check("a supplier is recommended", bool(result.get("recommended_supplier_name")))

    print(f"\n  {'Rank':<5}{'Supplier':<36}{'Score':<8}{'Landed':<12}{'Deliv':<7}{'Pay':<6}{'Cover'}")
    for s in suppliers_scored:
        landed = f"{s['landed_cost']:,.0f}" if s.get("landed_cost") is not None else "-"
        print(f"  {s['rank']:<5}{s['supplier_name'][:34]:<36}{s['overall_score']:<8.3f}"
              f"{landed:<12}{str(s.get('delivery_days') or '-'):<7}"
              f"{str(s.get('payment_days') if s.get('payment_days') is not None else '-'):<6}"
              f"{s.get('coverage')}")

    ranks = [s["rank"] for s in suppliers_scored]
    check("ranks are sequential from 1", ranks == list(range(1, len(ranks) + 1)), str(ranks))
    scores = [s["overall_score"] for s in suppliers_scored]
    check("scores are in descending order", scores == sorted(scores, reverse=True), str(scores))
    check("criterion breakdown present",
          all(len(s.get("criteria") or []) == 5 for s in suppliers_scored))
    check("missing-data flags present on at least one supplier",
          any(s.get("missing_data") for s in suppliers_scored))
    check("deduction reasons present",
          any(c.get("deductions") for s in suppliers_scored for c in s["criteria"]))

    explanation = result.get("ai_explanation") or {}
    check("explanation is present", explanation.get("available") is True, str(explanation)[:200])
    check("explanation source is labelled", bool(explanation.get("provider")), str(explanation.get("provider")))
    if not ai_configured:
        check("explanation correctly falls back to deterministic",
              explanation.get("provider") == "deterministic", str(explanation.get("provider")))
    print(f"  ..  explanation provider: {explanation.get('provider')}")
    print(f"  ..  summary: {(explanation.get('summary') or '')[:220]}")

    # Verify the AI did not alter the calculated ranking.
    stored = client.get(f"{API}/comparisons/procurement-requests/{request_id}", headers=auth_a).json()
    check("stored comparison matches computed ranking",
          [s["supplier_name"] for s in stored["suppliers"]] == [s["supplier_name"] for s in suppliers_scored])

    # ------------------------------------------------------------------
    section("10b. PHASES 4-6: DRAFTS, PURCHASE ORDERS, AGENTS, ANALYTICS")
    # ------------------------------------------------------------------
    top, runner_up = suppliers_scored[0], suppliers_scored[1]
    check("comparison rows carry a transport cost field", all("transport_cost" in s for s in suppliers_scored))

    runs = client.get(f"{API}/agents/runs?quotation_id={quotation_ids[0]}", headers=auth_a).json()
    check("processing ran as a recorded agent graph", bool(runs) and runs[0]["graph"] == "quotation_processing", str(runs)[:200])
    if runs:
        agents = [s["agent"] for s in runs[0]["steps"]]
        print(f"  ..  processing agents: {agents}")
        check("processing graph starts with the Document Extraction Agent", agents[:1] == ["Document Extraction Agent"])

    rfq = client.post(f"{API}/procurement-requests/{request_id}/rfqs", headers=auth_a,
                      json={"supplier_ids": [supplier_id]})
    check("RFQ draft created", rfq.status_code == 201, rfq.text[:300])
    rfq_draft = rfq.json()[0]
    check("RFQ lists the requested items",
          all(item["name"] in rfq_draft["body"] for item in created.json()["items"]), rfq_draft["body"][:300])
    check("RFQ records how it was written", rfq_draft["generated_by"] in ("ai", "template"))

    negotiation = client.post(f"{API}/comparisons/procurement-requests/{request_id}/negotiations", headers=auth_a,
                              json={"quotation_id": top["quotation_id"]})
    check("negotiation draft created", negotiation.status_code == 201, negotiation.text[:300])
    neg = negotiation.json()
    check("negotiation never names a competitor",
          all(s["supplier_name"] not in neg["body"] for s in suppliers_scored[1:]), neg["body"][:300])
    check("mark-sent before approval is refused",
          client.post(f"{API}/communications/{neg['id']}/mark-sent", headers=auth_a).status_code == 409)
    check("draft approves", client.post(f"{API}/communications/{neg['id']}/approve", headers=auth_a).json()["status"] == "approved")
    check("approved draft marked sent",
          client.post(f"{API}/communications/{neg['id']}/mark-sent", headers=auth_a).json()["status"] == "sent")
    eml = client.get(f"{API}/communications/{neg['id']}/eml", headers=auth_a)
    check(".eml export", eml.status_code == 200 and b"Subject:" in eml.content, eml.text[:200])

    sourcing = client.post(f"{API}/agents/sourcing/{request_id}", headers=auth_a)
    check("sourcing agents stop for approval",
          sourcing.status_code == 201 and sourcing.json()["status"] == "awaiting_approval", sourcing.text[:300])

    award = client.post(f"{API}/comparisons/procurement-requests/{request_id}/award", headers=auth_a,
                        json={"quotation_id": top["quotation_id"]})
    check("award creates a purchase order", award.status_code == 201, award.text[:300])
    po = award.json()
    print(f"  ..  {po.get('po_number')}: {len(po.get('lines', []))} lines, taxes "
          f"{[t['name'] for t in po.get('pricing', {}).get('taxes', [])]}, total {po.get('pricing', {}).get('total')}")
    check("PO lines come from matched items", len(po.get("lines", [])) >= 1)
    check("PO number format", str(po.get("po_number", "")).startswith("PO-"), str(po.get("po_number")))
    for action in ("approve", "issue"):
        client.post(f"{API}/purchase-orders/{po['id']}/{action}", headers=auth_a)
    delivered = client.post(f"{API}/purchase-orders/{po['id']}/deliver", headers=auth_a, json={}).json()
    check("delivery recorded with on-time flag", delivered.get("status") == "delivered" and delivered.get("on_time") is True,
          str(delivered)[:200])
    pdf = client.get(f"{API}/purchase-orders/{po['id']}/pdf", headers=auth_a)
    check("PO PDF renders", pdf.content.startswith(b"%PDF"))
    po_mail = client.get(f"{API}/communications?kind=purchase_order", headers=auth_a).json()
    check("approved PO produced a covering email draft", any(c["purchase_order_id"] == po["id"] for c in po_mail))

    spend = client.get(f"{API}/analytics/spend", headers=auth_a).json()
    check("spend counts the delivered PO", spend["orders"] == 1 and spend["total_spend"] == po["pricing"]["total"], str(spend)[:200])
    models = client.get(f"{API}/analytics/models", headers=auth_a).json()
    check("reliability model is loaded", models["reliability"]["available"] is True)
    awarded_supplier = client.get(f"{API}/suppliers/{po['supplier_id']}", headers=auth_a).json() if po.get("supplier_id") else {}
    ml = (awarded_supplier.get("reliability") or {}).get("ml")
    check("delivered supplier gets an ML late-delivery risk", bool(ml) and ml["method"] == "ml_model", str(ml)[:200])
    assistant = client.post(f"{API}/assistant/messages", headers=auth_a, json={"message": "hello"})
    check("assistant answers or explains it needs an LLM",
          assistant.status_code == 200 if ai_configured else assistant.status_code == 503, assistant.text[:200])

    # ------------------------------------------------------------------
    section("11. DASHBOARD (real data)")
    # ------------------------------------------------------------------
    dash = client.get(f"{API}/dashboard/summary", headers=auth_a)
    check("dashboard 200", dash.status_code == 200, dash.text[:200])
    d = dash.json()
    print(f"  ..  requests={d['procurement_requests']} quotations={d['quotations']} suppliers={d['suppliers']}")
    check("dashboard counts real quotations",
          d["quotations"]["total"] == len(quotation_ids), f"{d['quotations']['total']} vs {len(quotation_ids)}")
    check("dashboard counts real requests", d["procurement_requests"]["total"] >= 1)
    check("dashboard counts real suppliers", d["suppliers"]["total"] >= 2)
    check("dashboard has a 14-day trend", len(d.get("trend") or []) == 14)
    check("dashboard has recent activity", len(d.get("recent_activity") or []) > 0)

    # ------------------------------------------------------------------
    section("12. ORGANIZATION ISOLATION")
    # ------------------------------------------------------------------
    reg_b = client.post(
        f"{API}/auth/register",
        json={
            "name": "Rival User", "email": f"rival+{suffix}@other-co-demo.com",
            "password": "AnotherStrongPw1!", "organization_name": f"Other Co {suffix}",
        },
    )
    check("second org registers", reg_b.status_code == 201, reg_b.text[:200])
    token_b = reg_b.json()["access_token"]
    auth_b = {"Authorization": f"Bearer {token_b}"}
    check("orgs are distinct", reg_b.json()["organization"]["id"] != org_a_id)

    b_requests = client.get(f"{API}/procurement-requests", headers=auth_b).json()
    check("org B sees none of org A's requests",
          all(r["id"] != request_id for r in b_requests["items"]), str(b_requests["total"]))
    b_quotations = client.get(f"{API}/quotations", headers=auth_b).json()
    check("org B sees none of org A's quotations", b_quotations["total"] == 0, str(b_quotations["total"]))
    b_suppliers = client.get(f"{API}/suppliers", headers=auth_b).json()
    check("org B sees none of org A's suppliers", b_suppliers["total"] == 0, str(b_suppliers["total"]))

    check("org B cannot read org A's request by id",
          client.get(f"{API}/procurement-requests/{request_id}", headers=auth_b).status_code == 404)
    check("org B cannot read org A's quotation by id",
          client.get(f"{API}/quotations/{quotation_ids[0]}", headers=auth_b).status_code == 404)
    check("org B cannot read org A's supplier by id",
          client.get(f"{API}/suppliers/{supplier_id}", headers=auth_b).status_code == 404)
    check("org B cannot download org A's file",
          client.get(f"{API}/quotations/{quotation_ids[0]}/file", headers=auth_b).status_code == 404)
    check("org B cannot correct org A's quotation",
          client.post(f"{API}/quotations/{quotation_ids[0]}/corrections", headers=auth_b,
                      json={"corrections": {"items.0.unit_price": 1}}).status_code == 404)
    check("org B cannot compare org A's request",
          client.post(f"{API}/comparisons/procurement-requests/{request_id}", headers=auth_b,
                      json={}).status_code == 404)

    check("org B sees none of org A's purchase orders",
          client.get(f"{API}/purchase-orders", headers=auth_b).json() == [])
    check("org B sees none of org A's communications",
          client.get(f"{API}/communications", headers=auth_b).json() == [])
    check("org B cannot open org A's purchase order",
          client.get(f"{API}/purchase-orders/{po['id']}", headers=auth_b).status_code == 404)
    check("org B spend is empty", client.get(f"{API}/analytics/spend", headers=auth_b).json()["orders"] == 0)

    b_dash = client.get(f"{API}/dashboard/summary", headers=auth_b).json()
    check("org B dashboard is empty", b_dash["quotations"]["total"] == 0, str(b_dash["quotations"]))

    # ------------------------------------------------------------------
    section("RESULTS")
    # ------------------------------------------------------------------
    print(f"  passed: {len(PASSED)}")
    print(f"  failed: {len(FAILED)}")
    for failure in FAILED:
        print(f"    - {failure}")
    client.close()
    return 1 if FAILED else 0


def _mime(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".csv": "text/csv",
    }.get(ext, "application/octet-stream")


if __name__ == "__main__":
    raise SystemExit(main())
