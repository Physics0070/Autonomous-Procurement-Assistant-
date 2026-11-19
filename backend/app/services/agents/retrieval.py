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


# ---------------------------------------------------------------------------
# Meaning-based search (embeddings) layered over the keyword search above
# ---------------------------------------------------------------------------
import hashlib  # noqa: E402
import logging  # noqa: E402
from statistics import median  # noqa: E402

import numpy as np  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer as _CharTfidf  # noqa: E402

logger = logging.getLogger(__name__)

_CACHE: dict[str, np.ndarray] = {}
_CACHE_MAX = 2000  # ponytail: FIFO eviction; a vector store only matters once records number in the thousands
_BATCH = 40
MIN_MEANING = 0.62  # cosine below this is "unrelated" for gemini-embedding-001 (measured: related 0.68, unrelated 0.49)
_embedder = None
_embedder_resolved = False


def embedding_provider():
    """The model that turns text into vectors: LLM_TASK_MODELS "embedding=..." or Gemini's when its key is set."""
    global _embedder, _embedder_resolved
    if not _embedder_resolved:
        from app.core.config import settings
        from app.integrations.ai.factory import build_model, task_models

        spec = task_models().get("embedding") or ("gemini:gemini-embedding-001" if settings.GEMINI_API_KEY else None)
        _embedder = build_model(spec) if spec else None
        _embedder_resolved = True
    return _embedder


async def _vectors(embedder, texts: list[str]) -> Optional[np.ndarray]:
    """Unit vectors for the texts, from a small in-process cache; None if the embedder fails."""
    keys = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in texts]
    missing = [(k, t) for k, t in dict.fromkeys(zip(keys, texts)) if k not in _CACHE]
    for start in range(0, len(missing), _BATCH):
        batch = missing[start:start + _BATCH]
        result = await embedder.embed([t for _, t in batch])
        if result is None:
            return None
        for (key, _), vector in zip(batch, result):
            v = np.asarray(vector, dtype=np.float32)
            _CACHE[key] = v / (np.linalg.norm(v) or 1.0)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.pop(next(iter(_CACHE)))
    return np.vstack([_CACHE[k] for k in keys])


async def asearch(chunks: list[dict[str, Any]], query: str, embedder=None, k: int = 5) -> list[dict[str, Any]]:
    """Keyword search plus meaning: "tubing" finds "pipe". Falls back to keywords alone if embeddings are unavailable."""
    keyword = search(chunks, query, k=len(chunks) or 1)
    if embedder is None or not chunks or not (query or "").strip():
        return keyword[:k]
    base = {h["id"]: h for h in keyword}
    try:
        matrix = await _vectors(embedder, [c["text"] for c in chunks] + [query])
    except Exception as exc:  # embeddings are an extra; never break the assistant over them
        logger.warning("Embedding search unavailable: %s", exc)
        matrix = None
    if matrix is None:
        return keyword[:k]
    cosine = matrix[:-1] @ matrix[-1]
    rows = []
    for chunk, cos in zip(chunks, cosine):
        kw = base.get(chunk["id"], {}).get("match", 0.0)
        if kw < MIN_SCORE and cos < MIN_MEANING:
            continue
        meaning = min(max((float(cos) - 0.5) / 0.35, 0.0), 1.0)
        rows.append({"kind": chunk["kind"], "id": chunk["id"], "title": chunk["title"],
                     "match": round(0.5 * kw + 0.5 * meaning, 3), "excerpt": chunk["text"][:SNIPPET_CHARS]})
    return sorted(rows, key=lambda r: r["match"], reverse=True)[:k]


# ---------------------------------------------------------------------------
# What was paid before for similar items (works across different spellings and words)
# ---------------------------------------------------------------------------

def price_rows(quotations: list[dict]) -> list[dict[str, Any]]:
    rows = []
    for q in quotations:
        data = q.get("effective_data") or q.get("normalized_data") or {}
        for item in data.get("items") or []:
            name, price = item.get("original_name") or item.get("normalized_name"), item.get("unit_price")
            if name and isinstance(price, (int, float)) and price > 0:
                rows.append({"quotation_id": q.get("id"), "supplier_id": str(q.get("supplier_id") or ""),
                             "supplier_name": q.get("supplier_name"), "item": str(name), "unit_price": float(price),
                             "date": str(q.get("created_at") or "")[:10]})
    return rows


async def similar_prices(rows: list[dict[str, Any]], item: str, embedder=None, k: int = 8,
                         exclude_quotation: Optional[str] = None) -> list[dict[str, Any]]:
    """Past price rows for items like `item`, most similar first, each with a 0-1 similarity."""
    rows = [r for r in rows if r["quotation_id"] != exclude_quotation]
    if not rows or not (item or "").strip():
        return []
    names = [r["item"] for r in rows]
    # Character n-grams cope with OCR spacing ("PVCELBOW-2INCH" vs "PVC ELBOW - 2 INCH").
    vec = _CharTfidf(analyzer="char_wb", ngram_range=(3, 5), lowercase=True)
    try:
        matrix = vec.fit_transform([n.replace(" ", "") for n in names] + [item.replace(" ", "")])
        lexical = (matrix[:-1] @ matrix[-1].T).toarray().ravel()
    except ValueError:
        lexical = np.zeros(len(rows))
    meaning = np.zeros(len(rows))
    if embedder is not None:
        try:
            vectors = await _vectors(embedder, names + [item])
            if vectors is not None:
                meaning = np.clip((vectors[:-1] @ vectors[-1] - 0.5) / 0.35, 0.0, 1.0)
        except Exception as exc:
            logger.warning("Embedding price lookup unavailable: %s", exc)
    score = np.maximum(lexical, meaning)
    order = np.argsort(-score)[:k]
    return [{**rows[i], "similarity": round(float(score[i]), 2)} for i in order if score[i] >= 0.35]


def price_summary(found: list[dict[str, Any]]) -> dict[str, Any]:
    """Anonymous range for a negotiation: no supplier names, so nothing about a competitor can leak."""
    prices = [r["unit_price"] for r in found]
    if not prices:
        return {"observations": 0}
    return {"observations": len(prices), "lowest": min(prices), "median": round(float(median(prices)), 2), "highest": max(prices)}
