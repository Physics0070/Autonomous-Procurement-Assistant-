"""Analytics results are cached per organisation, keyed by the data's own count and last-updated time,
so a repeat visit is cheap and a change (new or updated order) is never hidden behind a stale cache."""
from bson import ObjectId

from app.repositories.base import utcnow
from app.services.analytics import cache
from tests.test_analytics import delivered_po


async def test_the_result_is_reused_until_the_data_changes(db):
    org = ObjectId()
    collection = db["analytics_cache_probe"]
    calls = []

    async def compute():
        calls.append(1)
        return {"rows": await collection.count_documents({"organization_id": org})}

    async def read():
        return await cache.cached("probe", str(org), [collection], compute)

    await collection.insert_one({"organization_id": org, "updated_at": utcnow()})
    assert (await read())["rows"] == 1 and (await read())["rows"] == 1
    assert len(calls) == 1                                   # second read came from the cache

    await collection.insert_one({"organization_id": org, "updated_at": utcnow()})
    assert (await read())["rows"] == 2 and len(calls) == 2   # a new row invalidates it

    await collection.update_one({"organization_id": org}, {"$set": {"updated_at": utcnow()}})
    await read()
    assert len(calls) == 3                                   # so does an edit (same count, newer timestamp)
    await collection.drop()


async def test_each_organisation_and_key_has_its_own_entry(db):
    first, second = ObjectId(), ObjectId()
    collection = db["analytics_cache_probe2"]
    await collection.insert_many([{"organization_id": first, "updated_at": utcnow()}, {"organization_id": second, "updated_at": utcnow()}])
    seen = []

    def make(tag):
        async def compute():
            seen.append(tag)
            return tag
        return compute

    assert await cache.cached("a", str(first), [collection], make("a1")) == "a1"
    assert await cache.cached("a", str(second), [collection], make("a2")) == "a2"
    assert await cache.cached("b", str(first), [collection], make("b1")) == "b1"
    assert await cache.cached("a", str(first), [collection], make("again")) == "a1"
    assert seen == ["a1", "a2", "b1"]
    await collection.drop()


async def test_the_spend_endpoint_recomputes_only_when_an_order_changes(api, sourcing, monkeypatch):
    from app.api.routes import analytics

    h, runs, real = sourcing["headers"], [], analytics.spend_summary

    def counting(*args, **kwargs):
        runs.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(analytics, "spend_summary", counting)
    cache.CACHE.clear()
    await delivered_po(api, sourcing, 0)
    first = (await api.get("/api/v1/analytics/spend", headers=h)).json()
    again = (await api.get("/api/v1/analytics/spend", headers=h)).json()
    assert first == again and len(runs) == 1

    await delivered_po(api, sourcing, 3)
    changed = (await api.get("/api/v1/analytics/spend", headers=h)).json()
    assert changed["orders"] == 2 and len(runs) == 2         # the new order shows up immediately


async def test_supplier_risk_predictions_are_reused_until_an_order_changes(api, sourcing, monkeypatch):
    from app.api.routes import suppliers

    h, runs, real = sourcing["headers"], [], suppliers.predict_all

    def counting(*args, **kwargs):
        runs.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(suppliers, "predict_all", counting)
    cache.CACHE.clear()
    await delivered_po(api, sourcing, 0)
    first = (await api.get("/api/v1/suppliers", headers=h)).json()["items"]
    second = (await api.get("/api/v1/suppliers", headers=h)).json()["items"]
    assert first == second and len(runs) == 1

    await delivered_po(api, sourcing, 5)
    await api.get("/api/v1/suppliers", headers=h)
    assert len(runs) == 2                                    # a new delivery changes the risk, so it is recomputed


async def test_quotation_counts_per_supplier_come_from_one_query(api, sourcing):
    listed = (await api.get("/api/v1/suppliers", headers=sourcing["headers"])).json()["items"]
    counts = {s["name"]: s["quotation_count"] for s in listed}
    assert counts == {"Shree Steel": 1, "Apex Metals": 1}   # same numbers as the per-supplier count it replaces
