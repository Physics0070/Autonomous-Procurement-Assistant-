"""The caller's own organization profile (buyer details on purchase orders)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, RequestContext, org_repo, require_roles
from app.core.errors import NotFoundError
from app.core.gstin import state_code, state_name
from app.repositories.users import OrganizationRepository
from app.schemas.auth import OrganizationOut, OrganizationUpdate
from app.schemas.common import UserRole

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("/me", response_model=OrganizationOut)
async def get_my_organization(context: CurrentUser) -> OrganizationOut:
    return OrganizationOut.model_validate(context.organization)


@router.put("/me", response_model=OrganizationOut)
async def update_my_organization(
    payload: OrganizationUpdate,
    context: RequestContext = Depends(require_roles(UserRole.ADMIN, UserRole.PROCUREMENT_MANAGER)),
    organizations: OrganizationRepository = Depends(org_repo),
) -> OrganizationOut:
    fields = payload.model_dump(exclude_unset=True)
    if "gst_number" in fields:
        # The GSTIN is authoritative for the state; it decides CGST/SGST vs IGST.
        fields["state_code"] = state_code(fields["gst_number"])
        if fields["gst_number"]:
            fields["state"] = state_name(fields["gst_number"])
    updated = await organizations.update_profile(context.organization_id, fields)
    if updated is None:
        raise NotFoundError("Organization not found")
    return OrganizationOut.model_validate(updated)
