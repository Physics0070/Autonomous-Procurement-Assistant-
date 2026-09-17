"""Channel connections: connect Gmail, collect from it, disconnect it.

WhatsApp is listed as planned - the synopsis scopes it as future support.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse

from app.api.deps import (
    CurrentUser,
    RequestContext,
    channel_repo,
    quotation_repo,
    require_roles,
    storage,
    supplier_repo,
)
from app.core.config import settings
from app.core.crypto import TokenDecryptionError, decrypt_secret, encrypt_secret
from app.core.errors import ConfigurationError, NotFoundError
from app.core.security import create_oauth_state, verify_oauth_state
from app.integrations.ingestion.gmail_client import (
    GmailAPIError,
    GmailClient,
    build_authorize_url,
)
from app.repositories.channels import ChannelConnectionRepository
from app.repositories.quotations import QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.schemas.common import UserRole
from app.services.channels.gmail_sync import PROVIDER as GMAIL
from app.services.channels.gmail_sync import Enqueue, run_gmail_sync
from app.services.storage.base import StorageBackend
from app.workers.processing import get_processing_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels", tags=["channels"])

MANAGE_ROLES = (UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)


async def get_gmail_client() -> AsyncIterator[GmailClient]:
    async with httpx.AsyncClient(timeout=30.0) as http:
        yield GmailClient(http)


def get_enqueue() -> Enqueue:
    return get_processing_queue().enqueue


def _public(connection: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Connection fields safe to return. The encrypted token never leaves the server."""
    if connection is None:
        return {"connected": False, "status": "not_connected"}
    return {
        "connected": connection.get("status") == "connected",
        "status": connection.get("status"),
        "account_email": connection.get("account_email"),
        "scopes": connection.get("scopes") or [],
        "connected_at": connection.get("connected_at"),
        "last_synced_at": connection.get("last_synced_at"),
        "last_result": connection.get("last_result"),
        "last_error": connection.get("last_error"),
    }


@router.get("")
async def list_channels(
    context: CurrentUser,
    channels: ChannelConnectionRepository = Depends(channel_repo),
) -> dict[str, Any]:
    gmail = await channels.get_for_provider(context.organization_id, GMAIL)
    return {
        "gmail": {
            **_public(gmail),
            "configured": settings.google_configured,
            "sync_interval_minutes": settings.GMAIL_SYNC_INTERVAL_MINUTES,
            "query": settings.GMAIL_SYNC_QUERY,
        },
        "whatsapp": {
            "connected": False,
            "status": "planned",
            "configured": False,
            "message": (
                "WhatsApp Business collection is planned future work. It needs Meta's "
                "official WhatsApp Business Cloud API and a verified business account."
            ),
        },
    }


@router.get("/gmail/authorize")
async def gmail_authorize(
    context: RequestContext = Depends(require_roles(*MANAGE_ROLES)),
) -> dict[str, str]:
    if not settings.google_configured:
        raise ConfigurationError(
            "Gmail is not set up on this server. Add GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET to backend/.env and restart the backend."
        )
    state = create_oauth_state(
        organization_id=context.organization_id, user_id=context.user_id, provider=GMAIL
    )
    return {"authorize_url": build_authorize_url(state)}


@router.get("/gmail/callback", include_in_schema=False)
async def gmail_callback(
    state: str = Query(...),
    code: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    channels: ChannelConnectionRepository = Depends(channel_repo),
    client: GmailClient = Depends(get_gmail_client),
) -> RedirectResponse:
    """Google redirects the browser here, so there is no bearer token.

    The signed state is what identifies the organization and user.
    """

    def back(outcome: str, reason: Optional[str] = None) -> RedirectResponse:
        params = {"gmail": outcome}
        if reason:
            params["reason"] = reason
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/integrations?{urlencode(params)}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    try:
        claims = verify_oauth_state(state, provider=GMAIL)
    except jwt.PyJWTError:
        return back("error", "The connection link expired or wasn't issued by this app. Connect again.")
    if error or not code:
        return back("error", "Google access wasn't granted.")

    try:
        grant = await client.exchange_code(code)
        if not grant.refresh_token:
            return back(
                "error",
                "Google didn't grant offline access. Remove this app under your Google "
                "Account's third-party access, then connect again.",
            )
        account = await client.get_profile_email(grant.access_token)
    except (GmailAPIError, httpx.HTTPError) as exc:
        logger.warning("Gmail connect failed: %s", exc)
        return back("error", "Google rejected the connection request. Connect again.")

    await channels.upsert_for_provider(
        claims["org"],
        GMAIL,
        {
            "status": "connected",
            "account_email": account,
            "encrypted_refresh_token": encrypt_secret(grant.refresh_token),
            "scopes": grant.scope.split(),
            "connected_by": claims["sub"],
            "connected_at": datetime.now(timezone.utc),
            "last_error": None,
        },
    )
    return back("connected")


@router.post("/gmail/sync")
async def gmail_sync(
    context: RequestContext = Depends(require_roles(*MANAGE_ROLES)),
    channels: ChannelConnectionRepository = Depends(channel_repo),
    quotations: QuotationRepository = Depends(quotation_repo),
    suppliers: SupplierRepository = Depends(supplier_repo),
    store: StorageBackend = Depends(storage),
    client: GmailClient = Depends(get_gmail_client),
    enqueue: Enqueue = Depends(get_enqueue),
) -> dict[str, Any]:
    return await run_gmail_sync(
        organization_id=context.organization_id,
        client=client,
        channels=channels,
        quotations=quotations,
        suppliers=suppliers,
        storage=store,
        enqueue=enqueue,
    )


@router.delete("/gmail", status_code=status.HTTP_204_NO_CONTENT)
async def gmail_disconnect(
    context: RequestContext = Depends(require_roles(*MANAGE_ROLES)),
    channels: ChannelConnectionRepository = Depends(channel_repo),
    client: GmailClient = Depends(get_gmail_client),
) -> Response:
    connection = await channels.get_for_provider(context.organization_id, GMAIL)
    if connection is None:
        raise NotFoundError("Gmail is not connected.")
    try:
        await client.revoke(decrypt_secret(connection["encrypted_refresh_token"]))
    except (TokenDecryptionError, httpx.HTTPError, KeyError) as exc:
        # Removing our copy still disconnects; the user can also revoke in Google.
        logger.warning("Could not revoke Gmail token for org %s: %s", context.organization_id, exc)
    await channels.delete_for_provider(context.organization_id, GMAIL)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
