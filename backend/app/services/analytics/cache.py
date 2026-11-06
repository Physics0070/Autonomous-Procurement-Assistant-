"""Per-organisation result cache for analytics, keyed by the data itself.

An entry is valid while every watched collection still has the same document count and the same latest
`updated_at` for that organisation. Both come from one cheap aggregate (~0.1 s on 10,000 orders), so a repeat
visit costs that instead of seconds of reading and computing, and a new or edited order is never hidden
behind a stale cache. Nothing expires on a timer.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Sequence

from app.repositories.base import to_object_id

# (key, organisation id) -> (fingerprint, value). ponytail: process-local; share it (Redis) if you run several workers.
CACHE: dict[tuple[str, str], tuple[tuple, Any]] = {}
MAX_ENTRIES = 256


async def fingerprint(collections: Sequence[Any], organization_id: str) -> tuple:
    org = to_object_id(organization_id)
    parts = []
    for collection in collections:
        rows = await collection.aggregate([
            {"$match": {"organization_id": org}},
            {"$group": {"_id": None, "n": {"$sum": 1}, "latest": {"$max": "$updated_at"}}},
        ]).to_list(length=1)
        parts.append((rows[0]["n"], rows[0]["latest"]) if rows else (0, None))
    return tuple(parts)


async def cached(key: str, organization_id: str, collections: Sequence[Any], compute: Callable[[], Awaitable[Any]]) -> Any:
    """`compute()` runs only when the organisation's data in `collections` has changed since the last call."""
    current = await fingerprint(collections, organization_id)
    entry = CACHE.get((key, organization_id))
    if entry is not None and entry[0] == current:
        return entry[1]
    value = await compute()
    if len(CACHE) >= MAX_ENTRIES:
        CACHE.clear()
    CACHE[(key, organization_id)] = (current, value)
    return value
