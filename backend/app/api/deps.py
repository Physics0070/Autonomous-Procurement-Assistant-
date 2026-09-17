"""Shared FastAPI dependencies.

The important one is `get_current_user`: it resolves the caller AND the
organization they belong to. Routes then pass `context.organization_id` into
org-scoped repositories, which is what enforces tenant isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import get_database
from app.core.security import decode_access_token
from app.repositories.procurement_requests import ProcurementRequestRepository
from app.repositories.quotations import ComparisonRepository, PriceHistoryRepository, QuotationRepository
from app.repositories.suppliers import SupplierRepository
from app.repositories.users import OrganizationRepository, UserRepository
from app.schemas.common import UserRole
from app.services.storage.base import StorageBackend
from app.services.storage.local import get_storage


@dataclass
class RequestContext:
    user: dict[str, Any]
    organization: dict[str, Any]

    @property
    def organization_id(self) -> str:
        return str(self.user["organization_id"])

    @property
    def user_id(self) -> str:
        return str(self.user["id"])

    @property
    def role(self) -> str:
        return str(self.user.get("role") or UserRole.MEMBER.value)


def db() -> AsyncIOMotorDatabase:
    return get_database()


DB = Annotated[AsyncIOMotorDatabase, Depends(db)]


def user_repo(database: DB) -> UserRepository:
    return UserRepository(database)


def org_repo(database: DB) -> OrganizationRepository:
    return OrganizationRepository(database)


def supplier_repo(database: DB) -> SupplierRepository:
    return SupplierRepository(database)


def request_repo(database: DB) -> ProcurementRequestRepository:
    return ProcurementRequestRepository(database)


def quotation_repo(database: DB) -> QuotationRepository:
    return QuotationRepository(database)


def comparison_repo(database: DB) -> ComparisonRepository:
    return ComparisonRepository(database)


def price_history_repo(database: DB) -> PriceHistoryRepository:
    return PriceHistoryRepository(database)


def storage() -> StorageBackend:
    return get_storage()


_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    authorization: Annotated[Optional[str], Header()] = None,
    users: UserRepository = Depends(user_repo),
    organizations: OrganizationRepository = Depends(org_repo),
) -> RequestContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _CREDENTIALS_ERROR
    token = authorization.split(" ", 1)[1].strip()

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.PyJWTError:
        raise _CREDENTIALS_ERROR

    user_id = payload.get("sub")
    if not user_id:
        raise _CREDENTIALS_ERROR

    user = await users.get(str(user_id))
    if user is None:
        raise _CREDENTIALS_ERROR

    organization = await organizations.get(str(user["organization_id"]))
    if organization is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization not found")

    # A token issued before the user moved organizations must not keep working
    # against the old one.
    token_org = payload.get("org")
    if token_org and str(token_org) != str(user["organization_id"]):
        raise _CREDENTIALS_ERROR

    return RequestContext(user=user, organization=organization)


CurrentUser = Annotated[RequestContext, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Route guard for role-restricted operations."""
    allowed = {r.value for r in roles}

    async def _guard(context: CurrentUser) -> RequestContext:
        if context.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires one of: {', '.join(sorted(allowed))}",
            )
        return context

    return _guard
