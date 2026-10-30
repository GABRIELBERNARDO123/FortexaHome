from __future__ import annotations

import uuid
from datetime import datetime

from app.schemas.common import APIModel


class LicenseStatusPublic(APIModel):
    id: uuid.UUID
    status: str
    code_last4: str
    product_name: str
    license_kind: str
    activated_at: datetime | None
    expires_at: datetime | None
