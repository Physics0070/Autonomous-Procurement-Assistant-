"""MongoDB connection management.

This module is the ONLY place that knows how to open a MongoDB connection.
Everything above the repository layer works with abstract repositories, so the
persistence engine can be swapped later without touching business logic.
"""
from __future__ import annotations

import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None


async def connect_to_database(uri: str | None = None, db_name: str | None = None) -> AsyncIOMotorDatabase:
    global _client, _db
    uri = uri or settings.MONGODB_URI
    db_name = db_name or settings.MONGODB_DB_NAME
    # tz_aware=True is required for correctness, not cosmetics: without it
    # MongoDB returns naive datetimes, which serialize without an offset and
    # are then parsed as local time by clients, shifting every timestamp.
    _client = AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=5000,
        uuidRepresentation="standard",
        tz_aware=True,
    )
    # Fail fast if MongoDB is unreachable.
    await _client.admin.command("ping")
    _db = _client[db_name]
    logger.info("Connected to MongoDB database '%s'", db_name)
    await ensure_indexes(_db)
    return _db


async def close_database_connection() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database is not initialised. Call connect_to_database() first.")
    return _db


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Create indexes required for correctness and multi-tenant isolation."""
    await db.users.create_index("email", unique=True)
    await db.users.create_index("organization_id")

    await db.organizations.create_index("name")

    await db.suppliers.create_index([("organization_id", 1), ("name", 1)])
    await db.suppliers.create_index([("organization_id", 1), ("email", 1)])

    await db.procurement_requests.create_index([("organization_id", 1), ("created_at", -1)])
    await db.procurement_requests.create_index([("organization_id", 1), ("status", 1)])

    await db.quotations.create_index([("organization_id", 1), ("created_at", -1)])
    await db.quotations.create_index([("organization_id", 1), ("processing_status", 1)])
    await db.quotations.create_index([("organization_id", 1), ("procurement_request_id", 1)])

    # One quotation per channel message part. Partial, so manual uploads
    # (which have no external reference) never collide.
    await db.quotations.create_index(
        [("organization_id", 1), ("source.external_reference", 1)],
        unique=True,
        partialFilterExpression={"source.external_reference": {"$type": "string"}},
        name="uniq_channel_reference",
    )
    await db.channel_connections.create_index(
        [("organization_id", 1), ("provider", 1)], unique=True, name="uniq_org_provider"
    )

    await db.comparisons.create_index([("organization_id", 1), ("procurement_request_id", 1)])
    await db.price_history.create_index([("organization_id", 1), ("normalized_name", 1)])
    await db.communications.create_index([("organization_id", 1), ("created_at", -1)])
    await db.purchase_orders.create_index([("organization_id", 1), ("created_at", -1)])
    await db.purchase_orders.create_index([("organization_id", 1), ("po_number", 1)], unique=True)
    await db.counters.create_index([("organization_id", 1), ("name", 1)], unique=True)
    logger.info("MongoDB indexes ensured")
