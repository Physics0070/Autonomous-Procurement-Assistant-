from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, org_repo, user_repo
from app.core.config import settings
from app.core.errors import AuthError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.repositories.users import OrganizationRepository, UserRepository
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    OrganizationOut,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.schemas.common import UserRole

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: dict, organization: dict) -> TokenResponse:
    token = create_access_token(
        subject=str(user["id"]),
        extra_claims={"org": str(user["organization_id"]), "role": user.get("role")},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(organization),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    users: UserRepository = Depends(user_repo),
    organizations: OrganizationRepository = Depends(org_repo),
) -> TokenResponse:
    """Register a user and create their organization.

    The first user of an organization becomes its admin.
    """
    existing = await users.get_by_email(payload.email)
    if existing is not None:
        raise ConflictError("An account with this email already exists.")

    organization = await organizations.create(payload.organization_name, payload.industry)
    user = await users.create(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        organization_id=str(organization["id"]),
        role=UserRole.ADMIN.value,
    )
    return _token_response(user, organization)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    users: UserRepository = Depends(user_repo),
    organizations: OrganizationRepository = Depends(org_repo),
) -> TokenResponse:
    user = await users.get_by_email_with_hash(payload.email)
    # Same error for unknown email and wrong password: do not leak which.
    if user is None or not verify_password(payload.password, user.get("hashed_password", "")):
        raise AuthError("Incorrect email or password.")

    organization = await organizations.get(str(user["organization_id"]))
    if organization is None:
        raise AuthError("Organization not found for this account.")
    return _token_response(user, organization)


@router.get("/me", response_model=MeResponse)
async def me(context: CurrentUser) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(context.user),
        organization=OrganizationOut.model_validate(context.organization),
    )
