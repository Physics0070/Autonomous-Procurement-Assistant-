"""Spend analytics, demand forecasts and the ML models behind them."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, RequestContext, quotation_repo, require_roles
from app.api.routes.automation import po_repo
from app.repositories.automation import PurchaseOrderRepository
from app.repositories.quotations import QuotationRepository
from app.schemas.common import UserRole
from app.services.analytics import reliability_ml
from app.services.analytics.spend import COMMITTED, spend_summary
from ml.anomaly import MIN_SAMPLES as ANOMALY_MIN_SAMPLES
from ml.forecast import MIN_MONTHS, forecast_demand, monthly_series

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/spend")
async def spend(context: CurrentUser, pos: PurchaseOrderRepository = Depends(po_repo),
                quotations: QuotationRepository = Depends(quotation_repo)) -> dict:
    return spend_summary(await pos.find_all(context.organization_id),
                         await quotations.list_filtered(context.organization_id, limit=500))


@router.get("/forecast")
async def forecast(context: CurrentUser, horizon: int = 3, pos: PurchaseOrderRepository = Depends(po_repo)) -> dict:
    """Monthly quantity per item from committed POs; items with < MIN_MONTHS months say so."""
    dates, quantities = defaultdict(list), defaultdict(list)
    for po in await pos.find_all(context.organization_id, {"status": {"$in": list(COMMITTED)}}):
        for line in po["lines"]:
            dates[line["description"]].append(po["created_at"])
            quantities[line["description"]].append(line["quantity"])
    items = [{"item": item, **forecast_demand(monthly_series(dates[item], quantities[item]), horizon=min(max(horizon, 1), 12))}
             for item in dates]
    return {"min_months": MIN_MONTHS, "items": sorted(items, key=lambda r: r["status"] != "ok")}


@router.get("/models")
async def models(context: CurrentUser) -> dict:
    model = reliability_ml.load_model(context.organization_id)
    meta = model.metadata if model else None
    return {
        "reliability": {"available": False, "reason": "Model artifact not found; rule-based scores are used."} if not meta else {
            "available": True,
            "own_data": reliability_ml.org_artifact_dir(context.organization_id).is_dir(),
            **{k: meta.get(k) for k in ("model_version", "model_name", "trained_at", "trained_on", "label",
                                         "feature_columns", "cv", "test", "baselines", "risk_bands", "train_period", "test_period")},
            "min_retrain_orders": reliability_ml.MIN_RETRAIN_ORDERS,
        },
        "price_anomaly": {"method": "isolation_forest", "min_samples": ANOMALY_MIN_SAMPLES,
                          "fallback": "z_score / deviation_ratio below the minimum"},
        "forecast": {"methods": ["linear_trend", "seasonal_naive"], "min_months": MIN_MONTHS},
    }


@router.post("/models/reliability/retrain")
async def retrain(context: RequestContext = Depends(require_roles(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)),
                  pos: PurchaseOrderRepository = Depends(po_repo)) -> dict:
    delivered = await pos.find_all(context.organization_id, {"status": {"$in": ["delivered", "closed"]}})
    meta = reliability_ml.retrain(context.organization_id, delivered)
    return {k: meta.get(k) for k in ("model_version", "model_name", "trained_on", "test", "baselines")}
