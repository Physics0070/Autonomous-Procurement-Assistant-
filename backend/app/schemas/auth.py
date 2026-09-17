from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import EmailStr, Field, field_validator

from app.core.gstin import is_valid_gstin, normalize_gstin

from app.schemas.common import APIModel, PyObjectId, UserRole


class OrganizationOut(APIModel):
    id: PyObjectId
    name: str
    industry: Optional[str] = None
    # Buyer details printed on purchase orders.
    address: Optional[str] = None
    gst_number: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    created_at: datetime


class OrganizationUpdate(APIModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    industry: Optional[str] = Field(default=None, max_length=120)
    address: Optional[str] = Field(default=None, max_length=1000)
    gst_number: Optional[str] = Field(default=None, max_length=20)
    state: Optional[str] = Field(default=None, max_length=80)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(default=None, max_length=40)

    @field_validator("gst_number")
    @classmethod
    def _valid_gstin(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        if not is_valid_gstin(value):
            raise ValueError("GSTIN must be 15 characters, e.g. 27AABCS1429B1ZQ.")
        return normalize_gstin(value)


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
