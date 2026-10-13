"""GET /boards/{name}/history — 单板块历史时序。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.db import fetch_board_history

router = APIRouter()


@router.get("/{name}/history")
async def board_history(name: str, days: int = Query(30, ge=1, le=365)) -> dict:
    """返回近 N 日 daily_metrics 时序，用于前端画时序图。"""
    rows = fetch_board_history(name, days=days)
    if not rows:
        raise HTTPException(status_code=404, detail=f"未找到板块 {name} 的历史数据")
    return {"board": name, "days": days, "history": rows}
