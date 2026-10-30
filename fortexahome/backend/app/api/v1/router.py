from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import (
    account,
    auth,
    bills,
    budgets,
    cards,
    categories,
    dashboard,
    goals,
    health,
    license,
    reports,
    transactions,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(account.router)
api_router.include_router(categories.router)
api_router.include_router(transactions.router)
api_router.include_router(bills.router)
api_router.include_router(cards.router)
api_router.include_router(budgets.router)
api_router.include_router(goals.router)
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)
api_router.include_router(license.router)
api_router.include_router(webhooks.router)
