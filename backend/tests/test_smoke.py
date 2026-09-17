"""The harness itself: database fixture, app transport and org sessions work."""


async def test_health_reports_a_connected_database(api):
    response = await api.get("/health")
    assert response.status_code == 200
    assert response.json()["database"]["connected"] is True


async def test_org_fixture_produces_a_working_session(api, org_a):
    response = await api.get("/api/v1/auth/me", headers=org_a["headers"])
    assert response.status_code == 200
    assert response.json()["organization"]["id"] == org_a["org_id"]


async def test_organizations_are_created_separately(org_a, org_b):
    assert org_a["org_id"] != org_b["org_id"]
