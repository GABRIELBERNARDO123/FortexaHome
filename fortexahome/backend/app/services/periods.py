from __future__ import annotations

import calendar
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status


def today_in_timezone(timezone_name: str) -> date:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("America/Sao_Paulo")
    return datetime.now(zone).date()


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def parse_month(value: str | None, timezone_name: str = "America/Sao_Paulo") -> date:
    if not value:
        today = today_in_timezone(timezone_name)
        return date(today.year, today.month, 1)
    try:
        return datetime.strptime(value, "%Y-%m").date().replace(day=1)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Mês inválido. Use o formato AAAA-MM"
        ) from exc


def parse_date_or_400(value: str, field: str = "data") -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"{field} inválida. Use AAAA-MM-DD"
        ) from exc


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1
