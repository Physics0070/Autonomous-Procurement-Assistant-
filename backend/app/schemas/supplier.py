from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import EmailStr, Field

from app.schemas.common import APIModel, PyObjectId


class SupplierBase(APIModel):
    """Suppliers routinely arrive with incomplete information - everything
    except the name is optional by design."""

    name: str = Field(min_length=1, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=40)
    gst_number: Optional[str] = Field(default=None, max_length=40)
    address: Optional[str] = Field(default=None, max_length=1000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SupplierCreate(SupplierBase):
    pass


class SupplierUpdate(APIModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    gst_number: Optional[str] = None
    address: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class SupplierReliability(APIModel):
    """Rule-based reliability. Explicitly NOT an ML prediction."""

    score: float = 0.5
    method: str = "rule_based"
    sample_size: int = 0
    factors: dict[str, Any] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SupplierOut(SupplierBase):
    id: PyObjectId
    organization_id: PyObjectId
    reliability: SupplierReliability = Field(default_factory=SupplierReliability)
    quotation_count: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None
