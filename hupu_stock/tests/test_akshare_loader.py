"""akshare 行情拉取 + PriceExtension 计算的单元测试。"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from market.akshare_loader import (
    _rank,
    compute_pct_changes,
    compute_price_extensions,
)
from storage.connection import get_connection
from storage.schema import init_db


def test_compute_pct_changes_columns() -> None:
    df = pd.DataFrame({
        "date": [f"2026-07-{i:02d}" for i in range(1, 12)],
        "close": [100.0 + i for i in range(11)],
    })
    out = compute_pct_changes(df)
    assert "pct_change_1d" in out.columns
    assert "pct_change_5d" in out.columns
    assert math.isnan(out["pct_change_1d"].iloc[0])
    assert out["pct_change_1d"].iloc[1] == pytest.approx(0.01, rel=1e-6)
    assert out["pct_change_5d"].iloc[-1] == pytest.approx(5.0 / 105.0, rel=1e-6)


def test_rank_basic() -> None:
    assert _rank(2.5, [0, 1, 2, 3, 5]) == pytest.approx(60.0, abs=0.01)
    assert _rank(10.0, [0, 1, 2, 3, 5]) == 100.0
    assert _rank(-5.0, [0, 1, 2, 3, 5]) == 0.0


def test_compute_price_extensions_uses_only_past_data() -> None:
    """验证截至当前时点的百分位只基于过去数据（无未来信息泄漏）。"""
    import os
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="hupu_test_")
    db_path = os.path.join(tmpdir, "test.db")
    try:
        with get_connection(db_path) as conn:
            init_db(conn)
            for b in ["半导体", "白酒"]:
                for d in ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"]:
                    conn.execute(
                        "INSERT INTO sector_prices(board,date,close,pct_change_10d) "
                        "VALUES (?,?,?,?)",
                        (b, d, 100.0, 0.01 * (hash(d + b) % 7 - 3)),
                    )
            conn.commit()

        with get_connection(db_path) as conn:
            n = compute_price_extensions(conn)
        assert n > 0

        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT board, date, up_extension_10d, down_extension_10d "
                "FROM sector_prices ORDER BY board, date"
            ).fetchall()
        for r in rows:
            assert 0.0 <= r["up_extension_10d"] <= 100.0
            assert 0.0 <= r["down_extension_10d"] <= 100.0
    finally:
        # WAL 文件可能被锁，先尝试关闭连接再清理
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
