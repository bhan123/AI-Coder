"""GET /boards/{name}/latest 与 /boards。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.db import fetch_board_latest, fetch_latest_snapshot_date, fetch_today_all

router = APIRouter()


@router.get("/")
async def list_boards() -> dict:
    """返回当前所有板块 + 是否 Top N + confidence + 当日状态（来自 fetch_today_all）。"""
    snapshot_date = fetch_latest_snapshot_date()
    boards = fetch_today_all(as_of_date=snapshot_date)
    return {"as_of_date": snapshot_date, "boards": boards}


@router.get("/{name}/latest")
async def board_latest(name: str) -> dict:
    """返回单板块当日完整指标 + Top 10 高热度帖子。"""
    result = fetch_board_latest(name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未找到板块 {name} 的指标")
    return result
