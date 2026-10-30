from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record(
    db: Session,
    event: str,
    *,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    entity: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    message: str | None = None,
) -> None:
    db.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            created_at=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            user_id=user_id,
            event=event,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
            message=message,
        )
    )
