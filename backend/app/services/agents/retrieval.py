"""Retrieval for the assistant: find the passages of the organization's own records that answer a question.

The assistant used to see only what its fixed tools returned. This adds search over the free text it could
not reach before: what each quotation says, and the e-mails already drafted or sent. Search is TF-IDF
(scikit-learn is already installed), so there is no new service to run. Every hit carries the record id and
kind, so an answer can be traced back, and a query that matches nothing returns nothing rather than a guess.
"""
from __future__ import annotations

from typing import Any, Optional

from sklearn.feature_extraction.text import TfidfVectorizer

MIN_SCORE = 0.08  # below this a hit is noise and is dropped
SNIPPET_CHARS = 320


def _quotation_chunk(q: dict[str, Any]) -> Optional[dict[str, Any]]:
    data = q.get("effective_data") or q.get("normalized_data") or {}
    items = data.get("items") or []
    lines = []
    for i in items[:40]:
        name = i.get("original_name") or i.get("normalized_name") or ""
        if not name:
            continue
        bits = [str(name)]
        if i.get("quantity") is not None:
            bits.append(f"qty {i.get('quantity')} {i.get('unit') or ''}".strip())
        if i.get("unit_price") is not None:
            bits.append(f"rate {i.get('unit_price')}")
        lines.append(" ".join(bits))
    terms = [str(v) for v in (data.get("payment_terms"), (data.get("delivery") or {}).get("terms")) if v]
    text = " ; ".join(lines + terms)
    if not text:
        return None
    supplier = q.get("supplier_name") or "unknown supplier"
    return {"kind": "quotation", "id": q.get("id"), "title": f"Quotation from {supplier}",
            "text": f"{supplier}. {text}"}


def _email_chunk(c: dict[str, Any]) -> Optional[dict[str, Any]]:
    body = " ".join(str(c.get(k) or "") for k in ("subject", "body")).strip()
    if not body:
        return None
    return {"kind": f"{c.get('kind') or 'email'} email ({c.get('status') or 'draft'})", "id": c.get("id"),
            "title": str(c.get("subject") or "Email"), "text": body}


def build_chunks(quotations: list[dict], communications: list[dict]) -> list[dict[str, Any]]:
    chunks = [_quotation_chunk(q) for q in quotations] + [_email_chunk(c) for c in communications]
    return [c for c in chunks if c]


def search(chunks: list[dict[str, Any]], query: str, k: int = 5) -> list[dict[str, Any]]:
    """Top-k chunks for the query, best first; empty when nothing is a real match."""
    if not chunks or not (query or "").strip():
        return []
    vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    try:
        matrix = vectorizer.fit_transform([c["text"] for c in chunks])
        scores = (matrix @ vectorizer.transform([query]).T).toarray().ravel()
    except ValueError:  # the query or the records held only stop words
        return []
    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:k]
    return [
        {"kind": chunks[i]["kind"], "id": chunks[i]["id"], "title": chunks[i]["title"],
         "match": round(float(scores[i]), 3), "excerpt": chunks[i]["text"][:SNIPPET_CHARS]}
        for i in ranked if scores[i] >= MIN_SCORE
    ]
