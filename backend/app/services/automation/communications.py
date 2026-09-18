"""RFQ and negotiation drafts, the negotiation guardrail, the status machine, .eml export.

The app never sends email: a person approves a draft, sends it from their own
mail client, and marks it sent.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any, Optional

from app.core.config import settings
from app.core.errors import ConflictError
from app.integrations.ai.base import AIProvider

DRAFT_SYSTEM = (
    "You write short, polite, professional procurement emails for an Indian buyer. "
    'Reply with JSON only: {"subject": "...", "body": "..."}. Plain text body, no markdown. '
    "Use only the facts given. Never mention any supplier other than the recipient."
)

# action -> (statuses it is allowed from, resulting status)
TRANSITIONS = {
    "approve": ({"draft"}, "approved"),
    "mark_sent": ({"approved"}, "sent"),
    "cancel": ({"draft", "approved"}, "cancelled"),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def history_entry(action: str, user_id: str, **details: Any) -> dict[str, Any]:
    return {"action": action, "by": user_id, "at": now(), **details}


def _money(value: Optional[float], currency: str = "INR") -> str:
    return f"{currency} {value:,.2f}" if value is not None else "not stated"


# ---------------------------------------------------------------------------
# Templates (always available; used when the LLM is unavailable or unsafe)
# ---------------------------------------------------------------------------


def rfq_template(request: dict, supplier: dict, buyer: dict) -> tuple[str, str]:
    lines = []
    for n, item in enumerate(request.get("items") or [], 1):
        qty = f"{item['quantity']:g} {item.get('unit') or ''}".strip() if item.get("quantity") is not None else "quantity to be confirmed"
        spec = f" - {item['specifications']}" if item.get("specifications") else ""
        lines.append(f"{n}. {item['name']}: {qty}{spec}")
    required_by = request.get("required_by")
    when = f"\nRequired by: {required_by:%d %b %Y}" if isinstance(required_by, datetime) else ""
    subject = f"Request for quotation: {request['title']}"
    body = (
        f"Dear {supplier.get('name') or 'Sir/Madam'},\n\n"
        f"{buyer.get('name', 'We')} invites your quotation for the following:\n\n"
        + "\n".join(lines)
        + f"\n{when}\n\n"
        "Please include unit prices, GST, freight, delivery time and payment terms, "
        "and reply to this email with your quotation (PDF or Excel).\n\n"
        f"Regards,\n{buyer.get('name', '')}\n{buyer.get('contact_email') or ''}"
    ).strip()
    return subject, body


def negotiation_asks(row: dict, target_price: Optional[float]) -> list[str]:
    asks = []
    if target_price is not None:
        asks.append(f"a revised total of {_money(target_price, row.get('currency') or 'INR')}")
    scores = {c["criterion"]: c.get("score", 1) for c in row.get("criteria") or []}
    weak = settings.NEGOTIATION_WEAK_CRITERION_SCORE
    if scores.get("delivery", 1) < weak:
        asks.append(f"faster delivery than {row.get('delivery_days') or 'the quoted'} days")
    if scores.get("payment", 1) < weak:
        asks.append(f"a longer credit period than {row.get('payment_days') or 0} days")
    return asks


def negotiation_template(row: dict, request: dict, buyer: dict, target_price: Optional[float]) -> tuple[str, str]:
    asks = negotiation_asks(row, target_price)
    subject = f"Regarding your quotation: {request['title']}"
    body = (
        f"Dear {row.get('supplier_name')},\n\n"
        f"Thank you for your quotation for {request['title']}. We would like to proceed, "
        "and ask you to consider:\n\n"
        + "\n".join(f"- {a}" for a in asks)
        + "\n\nWe look forward to your revised offer.\n\n"
        f"Regards,\n{buyer.get('name', '')}"
    )
    return subject, body


# ---------------------------------------------------------------------------
# Guardrail: a negotiation email must not reveal competitors.
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def check_negotiation_guardrail(text: str, recipient: str, rows: list[dict]) -> list[str]:
    findings = []
    lowered = text.lower()
    numbers = {float(n.replace(",", "")) for n in _NUMBER.findall(text)}
    for other in rows:
        name = other.get("supplier_name") or ""
        if not name or name == recipient:
            continue
        if name.lower() in lowered:
            findings.append(f"Names another supplier ({name}).")
        for amount in (other.get("total_cost"), other.get("landed_cost")):
            if amount and any(abs(n - amount) < 0.5 for n in numbers):
                findings.append(f"States another supplier's amount ({amount:,.2f}).")
    return findings


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------


async def _ai_draft(provider: Optional[AIProvider], prompt: str) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    if provider is None or not provider.is_configured():
        return None, (provider.configuration_error() if provider else "No AI provider.")
    response = await provider.generate(prompt, system=DRAFT_SYSTEM, json_mode=True, temperature=0.3)
    if not response.ok:
        return None, response.error
    try:
        data = json.loads(response.text)
        return (str(data["subject"]), str(data["body"])), None
    except (ValueError, KeyError, TypeError):
        return None, "The AI reply was not valid JSON with subject and body."


def _record(kind: str, subject: str, body: str, *, ai: bool, provider, reason, **fields) -> dict:
    return {
        "kind": kind,
        "status": "draft",
        "subject": subject,
        "body": body,
        "generated_by": "ai" if ai else "template",
        "provider": provider.name if ai else None,
        "model": provider.model if ai else None,
        "fallback_reason": None if ai else reason,
        "guardrail_findings": [],
        **fields,
    }


async def draft_rfqs(request: dict, suppliers: list[dict], buyer: dict, provider: Optional[AIProvider]) -> list[dict]:
    drafts = []
    for supplier in suppliers:
        subject, body = rfq_template(request, supplier, buyer)
        ai, reason = await _ai_draft(provider, f"Rewrite this RFQ email, keeping every item, quantity and date:\n\nSubject: {subject}\n\n{body}")
        drafts.append(_record(
            "rfq", *(ai or (subject, body)), ai=ai is not None, provider=provider, reason=reason,
            procurement_request_id=request["id"], supplier_id=supplier["id"], to_email=supplier.get("email"),
        ))
    return drafts


async def draft_negotiation(
    row: dict, rows: list[dict], request: dict, buyer: dict, provider: Optional[AIProvider],
    *, discount_pct: Optional[float] = None, target_price: Optional[float] = None, to_email: Optional[str] = None,
) -> dict:
    base = row.get("total_cost") or row.get("landed_cost")
    if discount_pct is None:
        discount_pct = settings.NEGOTIATION_DEFAULT_DISCOUNT_PCT
    if target_price is None and base:
        target_price = round(base * (1 - discount_pct / 100), 2)
    subject, body = negotiation_template(row, request, buyer, target_price)
    ai, reason = await _ai_draft(
        provider,
        f"Rewrite this negotiation email to {row.get('supplier_name')}. Keep every request and figure:\n\n"
        f"Subject: {subject}\n\n{body}",
    )
    findings = check_negotiation_guardrail(f"{ai[0]}\n{ai[1]}", row.get("supplier_name"), rows) if ai else []
    if findings:
        ai, reason = None, "The AI draft failed the guardrail; the template was used."
    record = _record(
        "negotiation", *(ai or (subject, body)), ai=ai is not None, provider=provider, reason=reason,
        procurement_request_id=request["id"], supplier_id=row.get("supplier_id"),
        quotation_id=row.get("quotation_id"), to_email=to_email, target_price=target_price,
    )
    record["guardrail_findings"] = findings
    return record


# ---------------------------------------------------------------------------
# Lifecycle and export
# ---------------------------------------------------------------------------


def transition(doc: dict, action: str, user_id: str) -> dict[str, Any]:
    """Return the $set/$push update for an action, or raise ConflictError."""
    allowed, target = TRANSITIONS[action]
    if doc["status"] not in allowed:
        raise ConflictError(f"Cannot {action.replace('_', ' ')} a communication that is {doc['status']}.")
    stamp = {"approve": "approved", "mark_sent": "sent", "cancel": "cancelled"}[action]
    return {
        "$set": {"status": target, f"{stamp}_by": user_id, f"{stamp}_at": now()},
        "$push": {"history": history_entry(action, user_id)},
    }


async def save_draft(repo, organization_id: str, user_id: str, draft: dict, **history: Any) -> dict:
    draft["created_by"] = user_id
    draft["history"] = [history_entry("created", user_id, generated_by=draft["generated_by"], **history)]
    return await repo.create(organization_id, draft)


def to_eml(doc: dict, sender: Optional[str]) -> bytes:
    message = EmailMessage()
    message["Subject"] = doc["subject"]
    if sender:
        message["From"] = sender
    if doc.get("to_email"):
        message["To"] = doc["to_email"]
    message["X-Unsent"] = "1"  # Outlook opens it as a draft
    message.set_content(doc["body"])
    return bytes(message)
