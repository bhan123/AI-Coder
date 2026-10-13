"""akshare 板块行情拉取。

数据源对比（2026-07 实测）：
- THS 同花顺：稳定可直连（沙箱内可用）
  - stock_board_industry_name_ths     行业名称 → code (90 条)
  - stock_board_industry_index_ths    单板块历史指数
- EM 东方财富：服务器环境通常可达；沙箱因代理可能不通
  - stock_board_industry_name_em
  - stock_board_industry_cons_em       成分股（THS 没有这个）
  - stock_board_industry_hist_em

第一版主用 THS 历史指数 + EM 成分股（如可用），全部失败时给出明确错误。
设计文档 §4.1 sector_prices 表 + §6：每个交易日 15:30 拉取板块行情。
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)


# -------- THS（主数据源）--------

def list_ths_industries() -> pd.DataFrame:
    """返回 90 条 (name, code) 同花顺行业列表。"""
    import akshare as ak
    return ak.stock_board_industry_name_ths()


def fetch_sector_index_ths(name: str, lookback_days: int = 400) -> pd.DataFrame:
    """单板块 THS 历史指数。返回至少包含 '日期' 与 '收盘价' 列的 DataFrame，按日期升序。

    沙箱实测：
    - 不传日期只回 2024-01-08（akshare 后端默认行为），
      这对 2026 年的真实环境不准；因此强制传 (今天-lookback_days, 今天)。
    - 400 天约等于 1.5 个自然年，覆盖 240+ 交易日。
    """
    import akshare as ak
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")
    df = ak.stock_board_industry_index_ths(symbol=name, start_date=start, end_date=end)
    df = df.rename(columns={
        "日期": "date", "开盘价": "open", "最高价": "high",
        "最低价": "low", "收盘价": "close",
        "成交量": "volume_shares", "成交额": "volume_yuan",
    })
    df = df.sort_values("date").reset_index(drop=True)
    return df


# -------- EM（成分股 fallback 服务器可用）--------

def fetch_sector_components_em(name: str) -> list[str] | None:
    """返回成分股名列表；EM 接口在代理环境会失败 → 返回 None 让调用方走 fallback。"""
    try:
        import akshare as ak
        df = ak.stock_board_industry_cons_em(symbol=name)
        # 列名 '名称' 或 '股票名称'，不同 akshare 版本略有差异
        col = next((c for c in df.columns if "名称" in c or "name" in c.lower()), None)
        if not col:
            return None
        return list(df[col].astype(str).head(30))
    except Exception as exc:
        logger.warning("成分股接口 EM 失败（%s）：%s", name, exc)
        return None


# -------- 计算衍生列 --------

def compute_pct_changes(df: pd.DataFrame) -> pd.DataFrame:
    """计算 pct_change_1d / 5d / 10d / 20d 百分比 (小数, 0.0123 == 1.23%)。"""
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["pct_change_1d"] = df["close"].pct_change()
    df["pct_change_5d"] = df["close"].pct_change(5)
    df["pct_change_10d"] = df["close"].pct_change(10)
    df["pct_change_20d"] = df["close"].pct_change(20)
    return df


# -------- SQLite upsert --------

def upsert_sector_prices(conn: sqlite3.Connection, board: str, df: pd.DataFrame) -> int:
    """写入 sector_prices 表。返回写入行数。"""
    cur = conn.cursor()
    n = 0
    for _, r in df.iterrows():
        cur.execute(
            """
            INSERT OR REPLACE INTO sector_prices
                (board, date, close, pct_change_1d, pct_change_5d, pct_change_10d, pct_change_20d)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                board, str(r.get("date", "")),
                float(r["close"]) if pd.notna(r.get("close")) else None,
                _pct(r.get("pct_change_1d")),
                _pct(r.get("pct_change_5d")),
                _pct(r.get("pct_change_10d")),
                _pct(r.get("pct_change_20d")),
            ),
        )
        n += 1
    conn.commit()
    return n


def _pct(x) -> float | None:
    if x is None or pd.isna(x):
        return None
    return float(x)


# -------- 历史分位（PriceExtension 用）--------

def compute_price_extensions(conn: sqlite3.Connection, lookback_days: int = 120) -> int:
    """为每条 sector_prices 计算 up_extension_10d / down_extension_10d 的历史分位 (0-100)。

    行为：
      - 历史窗口：lookback_days（默认 120）个交易日
      - up_extension: 当日 pct_change_10d 在历史上的百分位
      - down_extension: 当日 -pct_change_10d 在历史上的百分位
    返回被更新的行数。
    """
    cutoff = (datetime.now() - timedelta(days=int(lookback_days * 1.6))).date().isoformat()  # 多给一些缓冲
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT board, date, pct_change_10d
        FROM sector_prices
        WHERE pct_change_10d IS NOT NULL AND date >= ?
        ORDER BY board, date
        """,
        (cutoff,),
    ).fetchall()
    if not rows:
        return 0
    series_by_board: dict[str, list[tuple[str, float]]] = {}
    for b, d, p in rows:
        series_by_board.setdefault(b, []).append((d, p))

    n = 0
    for board, series in series_by_board.items():
        up_vals = [p for _, p in series]
        down_vals = [-p for _, p in series]
        # 按时间正序推每个时点的"截至此刻"百分位，避免未来信息
        for i, (date_str, p) in enumerate(series):
            up_pct = _rank(p, up_vals[: i + 1])
            down_pct = _rank(-p, down_vals[: i + 1])
            cur.execute(
                """
                UPDATE sector_prices
                SET up_extension_10d = ?, down_extension_10d = ?
                WHERE board = ? AND date = ?
                """,
                (up_pct, down_pct, board, date_str),
            )
            n += 1
    conn.commit()
    return n


def _rank(value: float, history: list[float]) -> float:
    if not history:
        return 50.0
    pct = sum(1 for h in history if h <= value) / len(history)
    return round(pct * 100, 2)


# -------- 顶层 entry --------

def refresh_one_sector(board: str, conn: sqlite3.Connection) -> dict:
    """拉一个板块的历史指数 + 写库 + 刷新 PriceExtension。"""
    df = fetch_sector_index_ths(board)
    df = compute_pct_changes(df)
    rows = upsert_sector_prices(conn, board, df)
    ext_rows = compute_price_extensions(conn)
    return {"board": board, "rows_written": rows, "extensions": ext_rows}


def refresh_all_known_boards(
    conn: sqlite3.Connection, boards: list[str], sleep_between: float = 1.5
) -> dict:
    """对列表里的每个板块按顺序拉（限速）。"""
    total = 0
    for i, b in enumerate(boards):
        try:
            r = refresh_one_sector(b, conn)
            total += r["rows_written"]
            logger.info("[%d/%d] %s: %s", i + 1, len(boards), b, r)
        except Exception as exc:
            logger.warning("[%d/%d] %s 失败：%s", i + 1, len(boards), b, exc)
        if i + 1 < len(boards):
            import time as _t
            _t.sleep(sleep_between)
    return {"total_rows": total, "boards_attempted": len(boards)}
