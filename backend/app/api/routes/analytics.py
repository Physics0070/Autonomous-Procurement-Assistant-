"""Spend analytics, demand forecasts and the ML models behind them."""
from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query

from app.api.deps import CurrentUser, RequestContext, quotation_repo, require_roles
from app.api.routes.automation import ai_provider, po_repo
from app.integrations.ai.base import AIProvider
from app.integrations.ai.factory import for_task
from app.repositories.automation import PurchaseOrderRepository
from app.repositories.quotations import QuotationRepository
from app.schemas.common import UserRole
from app.services.analytics import cache, reliability_ml
from app.services.analytics.spend import COMMITTED, spend_summary
from ml.anomaly import MIN_SAMPLES as ANOMALY_MIN_SAMPLES
from ml.forecast import MIN_MONTHS, forecast_demand, monthly_series

router = APIRouter(prefix="/analytics", tags=["analytics"])


# Only what spend_summary reads: fetching whole documents for 10,000 orders costs ~0.5 s more.
SPEND_FIELDS = ["status", "pricing.total", "pricing.currency", "supplier.name", "created_at", "lines.description",
                "lines.quantity", "lines.line_total", "procurement_request_id", "po_number", "on_time"]


@router.get("/spend")
async def spend(context: CurrentUser, pos: PurchaseOrderRepository = Depends(po_repo),
                quotations: QuotationRepository = Depends(quotation_repo)) -> dict:
    async def compute() -> dict:
        return spend_summary(await pos.find_all(context.organization_id, None, SPEND_FIELDS),
                             await quotations.list_filtered(context.organization_id, limit=500))
    return await cache.cached("spend", context.organization_id, [pos.collection, quotations.collection], compute)


@router.get("/forecast")
async def forecast(context: CurrentUser, horizon: int = 3, pos: PurchaseOrderRepository = Depends(po_repo)) -> dict:
    """Monthly quantity per item from committed POs; items with < MIN_MONTHS months say so."""
    horizon = min(max(horizon, 1), 12)

    async def compute() -> dict:
        dates, quantities = defaultdict(list), defaultdict(list)
        for po in await pos.find_all(context.organization_id, {"status": {"$in": list(COMMITTED)}},
                                     ["lines.description", "lines.quantity", "created_at"]):
            for line in po["lines"]:
                dates[line["description"]].append(po["created_at"])
                quantities[line["description"]].append(line["quantity"])
        items = [{"item": item, **forecast_demand(monthly_series(dates[item], quantities[item]), horizon=horizon)}
                 for item in dates]
        return {"min_months": MIN_MONTHS, "items": sorted(items, key=lambda r: r["status"] != "ok")}
    return await cache.cached(f"forecast:{horizon}", context.organization_id, [pos.collection], compute)


@router.get("/hsn")
async def suggest_hsn(context: CurrentUser, item: str = Query(min_length=2, max_length=300),
                      provider: AIProvider = Depends(ai_provider)) -> dict:
    """The HSN heading for a quotation line: the model's checked choice, or the best text match."""
    from ml.hsn import classify_hsn

    return await classify_hsn(item, for_task(provider, "hsn"))


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
