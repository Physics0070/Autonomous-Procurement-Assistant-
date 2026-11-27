"""Upload size is enforced before the body is held in memory."""
API = "/api/v1"


async def test_a_body_declared_larger_than_the_limit_is_refused_before_parsing(api, org_a):
    from app.core.config import settings

    too_big = str((settings.MAX_UPLOAD_SIZE_MB + 2) * 1024 * 1024)
    response = await api.post(f"{API}/documents/upload", headers={**org_a["headers"], "content-length": too_big}, content=b"x")
    assert response.status_code == 413


async def test_a_file_over_the_limit_is_refused_and_nothing_is_stored(api, org_a, monkeypatch, db):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 1)
    big = b"a,b\n" * (300 * 1024)  # 1.2 MB of CSV, under the 2 MB body allowance
    response = await api.post(f"{API}/documents/upload", headers=org_a["headers"], files={"file": ("q.csv", big, "text/csv")})
    assert response.status_code in (400, 422) and "1 MB" in response.text
    assert await db["quotations"].count_documents({"organization_id": org_a["org_id"]}) == 0
