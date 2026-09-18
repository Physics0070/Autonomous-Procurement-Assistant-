"""Phase 6 in the app: ML reliability from delivered POs, Isolation Forest anomalies, spend, forecast, models."""
from datetime import datetime, timedelta, timezone

from app.services.procurement.anomaly import detect_price_anomaly


def test_isolation_forest_is_used_from_20_prices():
    history = [100 + (i % 5) for i in range(25)]
    assert detect_price_anomaly(300, history=history)["method"] == "isolation_forest"
    assert detect_price_anomaly(300, history=history)["status"] == "HIGH_ANOMALY"
    assert detect_price_anomaly(101, history=history)["status"] == "NORMAL"
    assert detect_price_anomaly(300, history=history[:5])["method"] == "z_score"


async def delivered_po(api, s, days_late):
    h = s["headers"]
    po = (await api.post(f"/api/v1/comparisons/procurement-requests/{s['request']['id']}/award", headers=h,
                         json={"quotation_id": s["q_shree"]["id"]})).json()
    for action in ("approve", "issue"):
        await api.post(f"/api/v1/purchase-orders/{po['id']}/{action}", headers=h)
    when = datetime.now(timezone.utc) + timedelta(days=7 + days_late)
    return (await api.post(f"/api/v1/purchase-orders/{po['id']}/deliver", headers=h, json={"delivered_at": when.isoformat()})).json()


async def test_supplier_reliability_gets_an_ml_prediction_from_delivered_pos(api, sourcing):
    h = sourcing["headers"]
    assert (await api.get(f"/api/v1/suppliers/{sourcing['shree']['id']}", headers=h)).json()["reliability"]["ml"] is None
    for late in (0, 0, 5):
        await delivered_po(api, sourcing, late)
    supplier = (await api.get(f"/api/v1/suppliers/{sourcing['shree']['id']}", headers=h)).json()
    ml = supplier["reliability"]["ml"]
    assert ml["method"] == "ml_model" and 0 <= ml["late_probability"] <= 1 and ml["history_count"] >= 1
    assert "SCMS" in ml["trained_on"] and ml["test_metrics"]["roc_auc"] > 0.5
    assert supplier["reliability"]["method"] == "rule_based"  # fallback kept alongside
    listed = (await api.get("/api/v1/suppliers", headers=h)).json()["items"]
    assert {s["name"]: s["reliability"]["ml"] is not None for s in listed} == {"Shree Steel": True, "Apex Metals": False}


async def test_spend_forecast_models_and_retrain(api, sourcing):
    h = sourcing["headers"]
    await delivered_po(api, sourcing, 0)
    await delivered_po(api, sourcing, 3)
    spend = (await api.get("/api/v1/analytics/spend", headers=h)).json()
    assert spend["orders"] == 2 and spend["by_supplier"][0]["supplier"] == "Shree Steel"
    assert spend["by_supplier"][0]["on_time_rate"] == 0.5
    assert spend["savings"] == []  # a saving needs 2+ processed quotes with a total_amount
    assert {i["item"] for i in spend["by_item"]} == {"MS plate 10mm", "Hex bolt M12"}

    forecast = (await api.get("/api/v1/analytics/forecast", headers=h)).json()
    assert {i["status"] for i in forecast["items"]} == {"insufficient_data"}

    models = (await api.get("/api/v1/analytics/models", headers=h)).json()
    assert models["reliability"]["available"] and models["reliability"]["own_data"] is False

    retrain = await api.post("/api/v1/analytics/models/reliability/retrain", headers=h)
    assert retrain.status_code == 409 and "at least 50" in retrain.json()["error"]["message"]
