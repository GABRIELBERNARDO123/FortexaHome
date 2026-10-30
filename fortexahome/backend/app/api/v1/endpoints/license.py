from __future__ import annotations

from fastapi import APIRouter

from app.core.deps import CurrentAuth, DBSession
from app.models.product import Product
from app.schemas.license import LicenseStatusPublic

router = APIRouter(prefix="/license", tags=["licença"])


@router.get("", response_model=LicenseStatusPublic)
def license_status(ctx: CurrentAuth, db: DBSession) -> dict:
    license_row = ctx.license
    product = db.get(Product, license_row.product_id)
    return {
        "id": license_row.id,
        "status": license_row.status,
        "code_last4": license_row.code_last4,
        "product_name": product.name if product else "FortexaHome",
        "license_kind": product.license_kind if product else "lifetime",
        "activated_at": license_row.activated_at,
        "expires_at": license_row.expires_at,
    }
