from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import (
    agents,
    analytics,
    auth,
    automation,
    channels,
    organizations,
    comparison,
    dashboard,
    documents,
    procurement_requests,
    quotations,
    suppliers,
)
from app.core.config import settings
from app.core.database import close_database_connection, connect_to_database
from app.core.errors import AppError
from app.integrations.ai.factory import get_ai_provider
from app.services.documents.ocr import get_ocr_service
from app.workers.agent_monitor import get_agent_watchdog
from app.workers.channel_scheduler import get_channel_scheduler
from app.workers.processing import get_processing_queue, recover_pending_jobs

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_database()

    # Report capability status once at boot, so a degraded deployment is
    # obvious in the logs instead of surfacing as mysteriously poor results.
    ocr = get_ocr_service()
    engine = ocr.select()
    if engine:
        logger.info("OCR engine: %s (installed: %s)", engine.name, ", ".join(ocr.available_engines()))
    else:
        logger.warning("No OCR engine available - scanned documents and images cannot be read.")

    provider = get_ai_provider()
    if provider.is_configured():
        logger.info("AI provider: %s / %s", provider.name, provider.model)
    else:
        logger.warning("AI disabled: %s", provider.configuration_error())

    queue = get_processing_queue()
    await queue.start()
    scheduler = get_channel_scheduler()
    await scheduler.start()
    watchdog = get_agent_watchdog()
    await watchdog.start()
    try:
        await recover_pending_jobs()
    except Exception as exc:
        logger.warning("Could not recover pending jobs: %s", exc)

    yield

    await scheduler.stop()
    await watchdog.stop()
    await queue.stop()
    await close_database_connection()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.2.0",
    description=(
        "Autonomous Procurement Assistant - ingests messy supplier quotations "
        "(PDF, scanned PDF, images, Excel), extracts and normalizes them, and "
        "compares suppliers deterministically."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


def _serialisable_errors(errors: list[dict]) -> list[dict]:
    """Custom validators put the raised exception object in `ctx`; JSON can't hold it."""
    cleaned = []
    for error in errors:
        item = dict(error)
        if "ctx" in item:
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        item.pop("url", None)
        cleaned.append(item)
    return cleaned


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = _serialisable_errors(exc.errors())
    # Surface the first field message so the UI can show something specific.
    first = errors[0].get("msg") if errors else None
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "validation_error",
                "message": first.removeprefix("Value error, ") if first else "Request payload failed validation.",
                "details": {"errors": errors},
            }
        },
    )


@app.get("/health", tags=["system"])
async def health() -> dict:
    from app.core.database import get_database

    database_ok = True
    database_error = None
    try:
        await get_database().command("ping")
    except Exception as exc:
        database_ok = False
        database_error = str(exc)

    provider = get_ai_provider()
    engine = get_ocr_service().select()
    return {
        "status": "ok" if database_ok else "degraded",
        "database": {"connected": database_ok, "error": database_error, "name": settings.MONGODB_DB_NAME},
        "ai": {"configured": provider.is_configured(), "provider": provider.name},
        "ocr": {"available": engine is not None, "engine": engine.name if engine else None},
        "queue": {"depth": get_processing_queue().depth()},
        "version": app.version,
    }


for router in (
    auth.router,
    suppliers.router,
    procurement_requests.router,
    documents.router,
    quotations.router,
    comparison.router,
    dashboard.router,
    channels.router,
    organizations.router,
    automation.router,
    agents.router,
    agents.assistant_router,
    analytics.router,
):
    app.include_router(router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["system"])
async def root() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": app.version,
        "docs": "/docs",
        "api": settings.API_V1_PREFIX,
    }
