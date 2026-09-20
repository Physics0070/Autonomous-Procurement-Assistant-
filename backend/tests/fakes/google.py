"""An in-memory stand-in for Google's OAuth and Gmail REST endpoints.

Response shapes mirror the real API - `format=full` MIME trees, base64url
bodies, attachmentId references and `invalid_grant` errors - so the client is
exercised the way production traffic exercises it. Like real Gmail, attachment
IDs change on every message fetch; only the MIME partId is stable.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


@dataclass
class FakeAttachment:
    filename: str
    mime_type: str
    data: bytes
    inline: bool = False


@dataclass
class FakeMessage:
    id: str
    sender: str
    subject: str
    body: str = ""
    attachments: list[FakeAttachment] = field(default_factory=list)

    def to_full(self, attachment_ids: dict[str, str]) -> dict[str, Any]:
        headers = [
            {"name": "From", "value": self.sender},
            {"name": "To", "value": FakeGoogle.ACCOUNT},
            {"name": "Subject", "value": self.subject},
            {"name": "Date", "value": "Tue, 15 Sep 2026 10:12:00 +0530"},
        ]
        text_part = {
            "partId": "0.0",
            "mimeType": "text/plain",
            "filename": "",
            "headers": [{"name": "Content-Type", "value": "text/plain; charset=UTF-8"}],
            "body": {"size": len(self.body), "data": b64url(self.body.encode("utf-8"))},
        }
        html_part = {
            "partId": "0.1",
            "mimeType": "text/html",
            "filename": "",
            "headers": [{"name": "Content-Type", "value": "text/html; charset=UTF-8"}],
            "body": {"size": 0, "data": b64url(f"<p>{self.body}</p>".encode("utf-8"))},
        }
        parts: list[dict[str, Any]] = [
            {
                "partId": "0",
                "mimeType": "multipart/alternative",
                "filename": "",
                "headers": [],
                "body": {"size": 0},
                "parts": [text_part, html_part],
            }
        ]
        for index, attachment in enumerate(self.attachments, start=1):
            part_id = str(index)
            disposition = "inline" if attachment.inline else "attachment"
            parts.append(
                {
                    "partId": part_id,
                    "mimeType": attachment.mime_type,
                    "filename": attachment.filename,
                    "headers": [
                        {
                            "name": "Content-Disposition",
                            "value": f'{disposition}; filename="{attachment.filename}"',
                        }
                    ],
                    "body": {
                        "attachmentId": attachment_ids[part_id],
                        "size": len(attachment.data),
                    },
                }
            )
        return {
            "id": self.id,
            "threadId": f"thread-{self.id}",
            "labelIds": ["INBOX"],
            "snippet": self.body[:80],
            "internalDate": "1789457520000",
            "payload": {
                "partId": "",
                "mimeType": "multipart/mixed",
                "filename": "",
                "headers": headers,
                "body": {"size": 0},
                "parts": parts,
            },
        }


class FakeGoogle:
    ACCOUNT = "purchase@vishwakarma-eng.com"
    # Google returns the scopes the user actually consented to, which are the ones the
    # app asked for - Gmail reading plus Drive filing.
    SCOPE = ("https://www.googleapis.com/auth/gmail.readonly "
             "https://www.googleapis.com/auth/drive.file")

    def __init__(self) -> None:
        self.messages: dict[str, FakeMessage] = {}
        self.valid_codes = {"good-code"}
        self.valid_refresh_tokens = {"refresh-1"}
        self.valid_access_tokens: set[str] = set()
        self.revoked: list[str] = []
        self.requests: list[httpx.Request] = []
        self.omit_refresh_token = False
        self._attachment_data: dict[str, bytes] = {}
        self._issued = 0
        self._fetches = 0
        self._files = 0
        self.uploads: list[dict[str, Any]] = []

    def add_message(self, message: FakeMessage) -> None:
        self.messages[message.id] = message

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    # ------------------------------------------------------------------
    def handler(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "oauth2.googleapis.com" and path == "/token":
            return self._token(request)
        if host == "oauth2.googleapis.com" and path == "/revoke":
            form = parse_qs(request.content.decode())
            self.revoked.extend(form.get("token", []))
            return httpx.Response(200, json={})
        if host == "gmail.googleapis.com":
            return self._gmail(request)
        if host == "www.googleapis.com" and path.startswith("/upload/drive/v3/files"):
            return self._drive_upload(request)
        return httpx.Response(404, json={"error": f"unexpected host {host}"})

    def _issue_access_token(self) -> str:
        self._issued += 1
        token = f"ya29.access-{self._issued}"
        self.valid_access_tokens.add(token)
        return token

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        grant = form.get("grant_type")
        if grant == "authorization_code":
            if form.get("code") not in self.valid_codes:
                return httpx.Response(
                    400, json={"error": "invalid_grant", "error_description": "Bad Request"}
                )
            body = {
                "access_token": self._issue_access_token(),
                "expires_in": 3599,
                "scope": self.SCOPE,
                "token_type": "Bearer",
            }
            if not self.omit_refresh_token:
                body["refresh_token"] = "refresh-1"
            return httpx.Response(200, json=body)
        if grant == "refresh_token":
            if form.get("refresh_token") not in self.valid_refresh_tokens:
                return httpx.Response(
                    400,
                    json={
                        "error": "invalid_grant",
                        "error_description": "Token has been expired or revoked.",
                    },
                )
            return httpx.Response(
                200,
                json={
                    "access_token": self._issue_access_token(),
                    "expires_in": 3599,
                    "scope": self.SCOPE,
                    "token_type": "Bearer",
                },
            )
        return httpx.Response(400, json={"error": "unsupported_grant_type"})

    def _drive_upload(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_access_tokens:
            return httpx.Response(401, json={"error": {"code": 401, "message": "Invalid Credentials"}})
        # Pick the filename, type and bytes out of the multipart body the client sent.
        # CRLF is spelled out because a literal escape here is easy to mangle.
        crlf = bytes([13, 10])
        body = request.content
        name = re.search(rb'"name": ?"([^"]+)"', body)
        mime = re.search(rb"Content-Type: ([\w/.+-]+)" + crlf + crlf + rb"%PDF", body)
        data = body[body.index(b"%PDF"):].split(crlf + b"--")[0] if b"%PDF" in body else b""
        self._files += 1
        file_id = f"drive-file-{self._files}"
        self.uploads.append({
            "id": file_id,
            "name": name.group(1).decode() if name else "",
            "mime_type": mime.group(1).decode() if mime else "",
            "data": data,
        })
        return httpx.Response(200, json={
            "id": file_id, "name": self.uploads[-1]["name"],
            "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
        })

    def _gmail(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self.valid_access_tokens:
            return httpx.Response(
                401, json={"error": {"code": 401, "message": "Invalid Credentials"}}
            )
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        if path == "/profile":
            return httpx.Response(
                200,
                json={
                    "emailAddress": self.ACCOUNT,
                    "messagesTotal": 42,
                    "threadsTotal": 40,
                    "historyId": "12345",
                },
            )
        if path == "/messages":
            ids = sorted(self.messages)
            if not ids:
                return httpx.Response(200, json={"resultSizeEstimate": 0})
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": i, "threadId": f"thread-{i}"} for i in ids],
                    "resultSizeEstimate": len(ids),
                },
            )
        segments = path.strip("/").split("/")
        if len(segments) == 2 and segments[0] == "messages":
            message = self.messages.get(segments[1])
            if message is None:
                return httpx.Response(404, json={"error": {"code": 404}})
            self._fetches += 1
            attachment_ids = {}
            for index, attachment in enumerate(message.attachments, start=1):
                attachment_id = f"ANGjdJ-{message.id}-{index}-fetch{self._fetches}"
                self._attachment_data[attachment_id] = attachment.data
                attachment_ids[str(index)] = attachment_id
            return httpx.Response(200, json=message.to_full(attachment_ids))
        if len(segments) == 4 and segments[0] == "messages" and segments[2] == "attachments":
            data = self._attachment_data.get(segments[3])
            if data is None:
                return httpx.Response(404, json={"error": {"code": 404}})
            return httpx.Response(200, json={"size": len(data), "data": b64url(data)})
        return httpx.Response(404, json={"error": {"code": 404}})
