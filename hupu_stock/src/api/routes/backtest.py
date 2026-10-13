"""GET /backtest — 回测结果展示（设计文档 §7.1）。

设计 §11 验收点 13：至少 60 个交易日才有意义；当前路由返回 501 Not Implemented。
等价格数据 + 历史 sentiment 累计足够后再填实。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/")
async def list_backtest_boards() -> dict:
    """返回可回测的板块列表。"""
    raise HTTPException(
        status_code=501,
        detail="回测尚未实现。设计 §11 验收点 13 要求至少 60 个交易日数据 + is_top_board 信号稳定后再启用。",
    )


@router.get("/{name}")
async def backtest(
    name: str,
    holding_days: list[int] | None = Query(None),
) -> dict:
    """返回该板块 1/3/5/10/20 日的超额收益、胜率、最大回撤。"""
    raise HTTPException(
        status_code=501,
        detail=f"回测尚未实现（板块 {name}）。需要 60+ 个交易日的 Top N 数据 + akshare 价格历史（已具备）+ 防未来函数的时间序列对齐（待实现）。",
    )