from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import Field

from app.schemas.common import APIModel, ProcurementStatus, PyObjectId


class ProcurementItemBase(APIModel):
    name: str = Field(min_length=1, max_length=300)
    quantity: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = Field(default=None, max_length=40)
    specifications: Optional[str] = Field(default=None, max_length=4000)
    target_unit_price: Optional[float] = Field(default=None, ge=0)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProcurementItemIn(ProcurementItemBase):
    pass


class ProcurementItemOut(ProcurementItemBase):
    item_id: str
    normalized_name: Optional[str] = None
    normalized_tokens: List[str] = Field(default_factory=list)
    normalized_unit: Optional[str] = None
    normalized_quantity: Optional[float] = None


class ProcurementRequestCreate(APIModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = Field(default=None, max_length=8000)
    department: Optional[str] = Field(default=None, max_length=120)
    required_by: Optional[datetime] = None
    currency: str = "INR"
    status: ProcurementStatus = ProcurementStatus.OPEN
    items: List[ProcurementItemIn] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)


class ProcurementRequestUpdate(APIModel):
    title: Optional[str] = None
    description: Optional[str] = None
    department: Optional[str] = None
    required_by: Optional[datetime] = None
    currency: Optional[str] = None
    status: Optional[ProcurementStatus] = None
    items: Optional[List[ProcurementItemIn]] = None
    attributes: Optional[dict[str, Any]] = None


class ProcurementRequestOut(APIModel):
    id: PyObjectId
    organization_id: PyObjectId
    title: str
    description: Optional[str] = None
    department: Optional[str] = None
    required_by: Optional[datetime] = None
    currency: str = "INR"
    status: ProcurementStatus
    items: List[ProcurementItemOut] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    quotation_count: int = 0
    created_by: Optional[PyObjectId] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
