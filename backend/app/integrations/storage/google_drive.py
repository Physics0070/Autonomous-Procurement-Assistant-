"""Google Drive upload for generated purchase orders.

Scope is `drive.file`, which only grants access to files this app itself creates - it
cannot read the user's existing Drive. The refresh token is the one already stored for
the Gmail connection, so filing a PO needs no second sign-in.
"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.errors import UpstreamError

UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FIELDS = "id,name,webViewLink"


async def upload_file(http: httpx.AsyncClient, access_token: str, *, filename: str, data: bytes,
                      mime_type: str = "application/pdf", folder_id: str | None = None) -> dict[str, Any]:
    """Multipart upload: metadata part, then the bytes. Returns id, name and link."""
    metadata: dict[str, Any] = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]
    response = await http.post(
        UPLOAD_URL,
        params={"uploadType": "multipart", "fields": FIELDS},
        headers={"Authorization": f"Bearer {access_token}"},
        files={
            "metadata": (None, json.dumps(metadata), "application/json; charset=UTF-8"),
            "file": (filename, data, mime_type),
        },
    )
    if response.status_code >= 400:
        raise UpstreamError(f"Google Drive rejected the upload ({response.status_code}): {response.text[:200]}")
    body = response.json()
    return {"id": body.get("id"), "name": body.get("name") or filename,
            "link": body.get("webViewLink") or f"https://drive.google.com/file/d/{body.get('id')}/view"}
