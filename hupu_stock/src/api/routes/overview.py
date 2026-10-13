"""GET /overview — 今日全景。"""
from __future__ import annotations

from fastapi import APIRouter

from api.db import (
    fetch_global_stats,
    fetch_health_status,
    fetch_latest_snapshot_date,
    fetch_today_all,
)

router = APIRouter()


@router.get("/overview")
async def overview_today() -> dict:
    """今日全景：所有板块最新一条 daily_metrics + 全局概况。"""
    snapshot_date = fetch_latest_snapshot_date()
    boards = fetch_today_all(as_of_date=snapshot_date)
    return {
        "as_of_date": snapshot_date,
        "boards": boards,
        "stats": fetch_global_stats(as_of_date=snapshot_date),
        "health": fetch_health_status(),
    }
