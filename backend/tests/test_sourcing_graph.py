"""Sourcing graph: comparison -> recommendation -> negotiation, then it stops for a human."""


async def test_sourcing_prepares_a_draft_and_stops_for_approval(api, sourcing):
    h, request_id = sourcing["headers"], sourcing["request"]["id"]
    response = await api.post(f"/api/v1/agents/sourcing/{request_id}", headers=h)
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "awaiting_approval"
    assert [s["agent"] for s in run["steps"]] == ["Comparison Agent", "Recommendation Agent", "Negotiation Agent"]
    assert run["output"]["recommended_supplier_name"] == sourcing["comparison"]["recommended_supplier_name"]

    drafts = (await api.get("/api/v1/communications", headers=h)).json()
    assert [d["id"] for d in drafts] == run["output"]["communication_ids"]
    assert drafts[0]["kind"] == "negotiation" and drafts[0]["status"] == "draft"  # nothing approved or sent

    listed = (await api.get(f"/api/v1/agents/runs?procurement_request_id={request_id}", headers=h)).json()
    assert [r["id"] for r in listed] == [run["id"]]


async def test_sourcing_without_quotations_stops_after_comparison(api, org_a):
    h = org_a["headers"]
    request = (await api.post("/api/v1/procurement-requests", headers=h, json={"title": "Empty", "items": [{"name": "x"}]})).json()
    run = (await api.post(f"/api/v1/agents/sourcing/{request['id']}", headers=h)).json()
    assert run["status"] == "no_quotations" and len(run["steps"]) == 1
    assert (await api.get("/api/v1/communications", headers=h)).json() == []


async def test_runs_are_isolated(api, sourcing, org_b):
    run = (await api.post(f"/api/v1/agents/sourcing/{sourcing['request']['id']}", headers=sourcing["headers"])).json()
    assert (await api.get(f"/api/v1/agents/runs/{run['id']}", headers=org_b["headers"])).status_code == 404
    assert (await api.post(f"/api/v1/agents/sourcing/{sourcing['request']['id']}", headers=org_b["headers"])).status_code == 404
