"""Gmail REST API and Google OAuth 2.0 client.

Plain httpx rather than google-api-python-client: every call goes through one
injectable AsyncClient, so the integration is testable with httpx.MockTransport
and no Google account.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, Iterator, Optional
from urllib.parse import urlencode

import httpx

from app.core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GmailAuthError(GmailAPIError):
    """The stored grant no longer works; the user must reconnect."""


@dataclass
class TokenGrant:
    access_token: str
    refresh_token: Optional[str]
    expires_in: int
    scope: str


def google_scopes() -> str:
    """Everything this app asks Google for: Gmail reading, plus Drive when PO filing is on."""
    from app.integrations.storage.google_drive import SCOPE as DRIVE_SCOPE

    scopes = settings.GMAIL_SCOPES.split()
    if settings.GOOGLE_DRIVE_ENABLED and DRIVE_SCOPE not in scopes:
        scopes.append(DRIVE_SCOPE)
    return " ".join(scopes)


def build_authorize_url(state: str) -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": google_scopes(),
        # offline + consent guarantees a refresh token on every connect,
        # including a reconnect after the user revoked access.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def decode_base64url(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def header(message: dict[str, Any], name: str) -> Optional[str]:
    for item in (message.get("payload") or {}).get("headers") or []:
        if str(item.get("name", "")).lower() == name.lower():
            return item.get("value")
    return None


def parse_sender_email(from_header: Optional[str]) -> Optional[str]:
    if not from_header:
        return None
    _, address = parseaddr(from_header)
    address = address.strip().lower()
    return address if "@" in address else None


def iter_parts(part: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Depth-first walk over a MIME tree as returned by `format=full`."""
    yield part
    for child in part.get("parts") or []:
        yield from iter_parts(child)


def extract_plain_body(message: dict[str, Any]) -> str:
    chunks = []
    for part in iter_parts(message.get("payload") or {}):
        if part.get("mimeType") == "text/plain" and not part.get("filename"):
            data = (part.get("body") or {}).get("data")
            if data:
                chunks.append(decode_base64url(data).decode("utf-8", errors="replace"))
    return "\n".join(chunks).strip()


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class GmailClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    # -- OAuth ----------------------------------------------------------
    async def _token_request(self, form: dict[str, str]) -> dict[str, Any]:
        response = await self.http.post(GOOGLE_TOKEN_URL, data=form)
        body = _json(response)
        if response.status_code == 400 and body.get("error") == "invalid_grant":
            raise GmailAuthError(
                body.get("error_description") or "Google access was revoked or has expired.",
                status_code=400,
            )
        if response.status_code >= 400:
            raise GmailAPIError(
                f"Google token endpoint returned {response.status_code}: "
                f"{body.get('error', response.text[:200])}",
                status_code=response.status_code,
            )
        return body

    async def exchange_code(self, code: str) -> TokenGrant:
        body = await self._token_request(
            {
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            }
        )
        return TokenGrant(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_in=int(body.get("expires_in", 0)),
            scope=body.get("scope", ""),
        )

    async def refresh_access_token(self, refresh_token: str) -> str:
        body = await self._token_request(
            {
                "refresh_token": refresh_token,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "grant_type": "refresh_token",
            }
        )
        return body["access_token"]

    async def revoke(self, token: str) -> None:
        # Best effort: a token that is already invalid is already revoked.
        await self.http.post(GOOGLE_REVOKE_URL, data={"token": token})

    # -- Gmail ----------------------------------------------------------
    async def _get(
        self, access_token: str, path: str, params: Optional[dict[str, Any]] = None
    ) -> dict[str, Any]:
        response = await self.http.get(
            f"{GMAIL_API}{path}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code == 401:
            raise GmailAuthError("Gmail rejected the access token.", status_code=401)
        if response.status_code >= 400:
            raise GmailAPIError(
                f"Gmail API {path} returned {response.status_code}",
                status_code=response.status_code,
            )
        return _json(response)

    async def get_profile_email(self, access_token: str) -> str:
        body = await self._get(access_token, "/profile")
        return str(body["emailAddress"]).lower()

    async def list_message_ids(self, access_token: str, query: str, max_results: int) -> list[str]:
        ids: list[str] = []
        page_token: Optional[str] = None
        while len(ids) < max_results:
            params: dict[str, Any] = {"q": query, "maxResults": min(100, max_results - len(ids))}
            if page_token:
                params["pageToken"] = page_token
            body = await self._get(access_token, "/messages", params)
            ids.extend(item["id"] for item in body.get("messages") or [])
            page_token = body.get("nextPageToken")
            if not page_token:
                break
        return ids[:max_results]

    async def get_message(self, access_token: str, message_id: str) -> dict[str, Any]:
        return await self._get(access_token, f"/messages/{message_id}", {"format": "full"})

    async def get_attachment(self, access_token: str, message_id: str, attachment_id: str) -> bytes:
        body = await self._get(access_token, f"/messages/{message_id}/attachments/{attachment_id}")
        return decode_base64url(body["data"])
