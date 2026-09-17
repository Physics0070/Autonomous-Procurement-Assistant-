from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import EmailStr, Field

from app.schemas.common import APIModel, PyObjectId, UserRole


class OrganizationOut(APIModel):
    id: PyObjectId
    name: str
    industry: Optional[str] = None
    created_at: datetime


class RegisterRequest(APIModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    organization_name: str = Field(min_length=1, max_length=160)
    industry: Optional[str] = Field(default=None, max_length=120)


class LoginRequest(APIModel):
    email: EmailStr
    password: str


class UserOut(APIModel):
    id: PyObjectId
    name: str
    email: EmailStr
    role: UserRole
    organization_id: PyObjectId
    created_at: datetime


class MeResponse(APIModel):
    user: UserOut
    organization: OrganizationOut


class TokenResponse(APIModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
    organization: OrganizationOut
