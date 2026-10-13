from __future__ import annotations

import sys
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from app.data_provider import (
    AkshareHistoryProvider,
    AkshareIntradayProvider,
    AkshareSectorProvider,
    ContextAssembler,
    EastMoneySectorProvider,
    LiveSectorProvider,
)
from app.models import MarketSnapshot


def test_sector_provider_builds_stock_membership_from_board_codes(monkeypatch) -> None:
    requested_symbols: list[str] = []

    def industry_names() -> pd.DataFrame:
        return pd.DataFrame([
            {"板块代码": "BK0001", "板块名称": "强势板块", "涨跌幅": 2.6,
             "领涨股票": "甲公司", "领涨股票-涨跌幅": 5.2},
            {"板块代码": "BK0002", "板块名称": "次强板块", "涨跌幅": 1.1,
             "领涨股票": "乙公司", "领涨股票-涨跌幅": 3.4},
        ])

    def industry_members(symbol: str) -> pd.DataFrame:
        requested_symbols.append(symbol)
        members = {
            "BK0001": [{"代码": "000001", "名称": "甲公司"}],
            "BK0002": [{"代码": "600001", "名称": "乙公司"}],
        }
        return pd.DataFrame(members[symbol])

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_board_industry_name_em=industry_names,
        stock_board_industry_cons_em=industry_members,
    ))

    provider = AkshareSectorProvider()

    assert provider.sector_for_code("000001").code == "BK0001"
    assert provider.sector_for_code("600001").code == "BK0002"
    assert set(requested_symbols) == {"BK0001", "BK0002"}


def test_intraday_provider_calculates_cumulative_vwap_from_amount_and_volume(monkeypatch) -> None:
    frame = pd.DataFrame([
        {"时间": "2026-07-31 09:30:00", "收盘": 10.0, "成交量": 10, "成交额": 10_000},
        {"时间": "2026-07-31 09:31:00", "收盘": 12.0, "成交量": 20, "成交额": 24_000},
    ])
    requested: list[dict] = []

    def fetch_minute(**kwargs) -> pd.DataFrame:
        requested.append(kwargs)
        return frame.copy()

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_zh_a_hist_min_em=fetch_minute,
    ))

    bars = AkshareIntradayProvider().fetch(
        "000001", datetime(2026, 7, 31, 9, 31)
    )

    assert [bar.avg_price for bar in bars] == [10.0, pytest.approx(11.333333, rel=1e-6)]
    assert requested[0]["symbol"] == "000001"
    assert requested[0]["adjust"] == ""


def test_history_provider_uses_plain_six_digit_symbol(monkeypatch) -> None:
    frame = pd.DataFrame([
        {"日期": "2026-07-31", "开盘": 10.0, "最高": 10.5, "最低": 9.8,
         "收盘": 10.2, "成交量": 1000, "换手率": 2.1},
    ])
    requested: list[dict] = []

    def fetch_daily(**kwargs) -> pd.DataFrame:
        requested.append(kwargs)
        return frame.copy()

    monkeypatch.setitem(sys.modules, "akshare", SimpleNamespace(
        stock_zh_a_hist=fetch_daily,
    ))

    bars = AkshareHistoryProvider().fetch("600001", date(2026, 7, 31), limit=30)

    assert len(bars) == 1
    assert requested[0]["symbol"] == "600001"


def test_context_assembler_enriches_only_the_highest_priority_candidates() -> None:
    history_calls: list[str] = []
    intraday_calls: list[str] = []

    class HistorySpy:
        source_name = "spy history"

        def fetch(self, code, end, *, limit=30):
            history_calls.append(code)
            return []

    class IntradaySpy:
        source_name = "spy intraday"

        def fetch(self, code, captured_at):
            intraday_calls.append(code)
            return []

    class NoSectors:
        source_name = "none"

        def sector_for_code(self, code):
            return None

        def sectors(self):
            return []

    captured_at = datetime(2026, 7, 31, 14, 50)
    snapshots = [
        MarketSnapshot(code=code, name=code, price=10, pct_change=0, day_low=9.8,
                       turnover_rate=priority, volume_ratio=1, market_pct_change=0,
                       captured_at=captured_at)
        for code, priority in [("000001", 1), ("000002", 3), ("000003", 2)]
    ]
    contexts = ContextAssembler(HistorySpy(), IntradaySpy(), NoSectors()).assemble(
        snapshots,
        captured_at,
        enrich_limit=2,
        enrich_priority=lambda context: context.snapshot.turnover_rate,
    )

    assert set(contexts) == {"000001", "000002", "000003"}
    assert set(history_calls) == {"000002", "000003"}
    assert set(intraday_calls) == {"000002", "000003"}


def test_context_assembler_skips_sector_provider_when_strategy_does_not_need_it() -> None:
    class NoHistory:
        source_name = "none"

        def fetch(self, code, end, *, limit=30):
            return []

    class NoIntraday:
        source_name = "none"

        def fetch(self, code, captured_at):
            return []

    class RaisingSectors:
        source_name = "must not be called"

        def sector_for_code(self, code):
            raise AssertionError("sector lookup should be skipped")

        def sectors(self):
            raise AssertionError("sector list should be skipped")

    captured_at = datetime(2026, 7, 31, 14, 50)
    snapshot = MarketSnapshot(
        code="000001", name="样例", price=10, pct_change=1, day_low=9.8,
        turnover_rate=2, volume_ratio=1, market_pct_change=0, captured_at=captured_at,
    )
    contexts = ContextAssembler(NoHistory(), NoIntraday(), RaisingSectors()).assemble(
        [snapshot], captured_at, sector_required=False, history_required=False, intraday_required=False
    )

    assert contexts["000001"].sector is None


# ---------------------------------------------------------------------------
# ISSUE-4 (2026-08-06): NaN/inf volume_ratio 在 save_run 之前必须归零，否则
# market_snapshots.volume_ratio NOT NULL 约束会让 P2/P3/P4 整套策略 500 报错。
# ---------------------------------------------------------------------------


def test_volume_ratio_nan_is_coerced_to_zero_in_model() -> None:
    """pydantic field_validator 把 NaN volume_ratio 归 0.0."""
    snap = MarketSnapshot(
        code="000001", name="nan-test", price=10, pct_change=1, day_low=9.8,
        turnover_rate=2, volume_ratio=float("nan"), market_pct_change=0,
        captured_at=datetime(2026, 8, 6, 14, 50),
    )
    assert snap.volume_ratio == 0.0


def test_volume_ratio_inf_is_coerced_to_zero_in_model() -> None:
    snap = MarketSnapshot(
        code="000001", name="inf-test", price=10, pct_change=1, day_low=9.8,
        turnover_rate=2, volume_ratio=float("inf"), market_pct_change=0,
        captured_at=datetime(2026, 8, 6, 14, 50),
    )
    assert snap.volume_ratio == 0.0


def test_repository_save_run_coerces_nan_volume_ratio() -> None:
    """绕过 pydantic validator 直接构造快照时，repository 必须再次归零。

    复现 Aug 05 14:51 的真实报错：P2/P3/P4 因为 volume_ratio 为 NULL 整体失败。
    """
    import os
    import tempfile
    from app.repository import StrategyRepository
    from app.models import StrategyRun

    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    try:
        repo = StrategyRepository(db_path)
        run = StrategyRun(
            run_id="test-run", strategy_id="p3-platform-breakout", version="1.0.0",
            observed_at=datetime(2026, 8, 6, 14, 50), mode="live", capture_origin="scheduled",
            universe_size=1, data_source="Tencent + Sina composite",
            execution_status="tradable", signals=[],
        )
        raw_snapshot = MarketSnapshot.model_construct(
            code="000001", name="raw", price=10, pct_change=1, day_low=9.8,
            turnover_rate=2, volume_ratio=float("nan"), market_pct_change=0,
            captured_at=datetime(2026, 8, 6, 14, 50),
        )
        repo.save_run(run, snapshots=[raw_snapshot])

        import sqlite3
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT volume_ratio FROM market_snapshots").fetchone()
        assert row is not None and row[0] == 0.0
    finally:
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# ISSUE-5 (2026-08-06): akshare 用的 ``17.push2.eastmoney.com`` 域名在部署机
# 被屏蔽。增加 EastMoney 直连 + LiveSectorProvider 降级链路的测试。
# ---------------------------------------------------------------------------


def test_east_money_sector_provider_parses_list_payload(monkeypatch) -> None:
    """EM 接口成功时返回有效 SectorQuote 列表，且涨跌幅按基点正确换算。"""

    sample_payload = {
        "data": {
            "diff": {
                "0": {"f3": 250, "f12": "BK0424", "f14": "水泥",
                       "f128": "西藏天路", "f140": "600326", "f141": 502, "f105": 22},
                "1": {"f3": -190, "f12": "BK0421", "f14": "铁路公路",
                       "f128": "大众交通", "f140": "600611", "f141": 100, "f105": 9},
            }
        }
    }

    monkeypatch.setattr(
        "app.data_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            json=lambda: sample_payload,
            raise_for_status=lambda: None,
            text=str(sample_payload),
        ),
    )

    provider = EastMoneySectorProvider()
    sectors = provider.sectors()

    by_code = {s.code: s for s in sectors}
    assert "BK0424" in by_code
    assert by_code["BK0424"].name == "水泥"
    # f3 = 250 basis points → 2.50%
    assert by_code["BK0424"].pct_change == 2.5
    assert by_code["BK0424"].leader_code == "600326"
    assert by_code["BK0424"].leader_name == "西藏天路"
    # f141 = 502 basis points → 5.02%
    assert by_code["BK0424"].leader_pct_change == 5.02
    # limit_up_count 字段保留为 0（akshare 路径下也是 0）
    assert by_code["BK0424"].limit_up_count == 0


def test_live_sector_provider_falls_back_to_east_money_when_akshare_fails(monkeypatch) -> None:
    """akshare 抛错时，LiveSectorProvider 应自动切换到 EastMoneySectorProvider。"""

    class _BrokenAkshare:
        source_name = "broken-akshare"

        def sectors(self):
            raise RuntimeError("akshare 行业板块列表失败: ConnectionError")

        def sector_for_code(self, code):
            raise RuntimeError("akshare 行业板块列表失败: ConnectionError")

    # monkeypatch 掉 AkshareSectorProvider 类，让其实例化就抛错
    import app.data_provider as dp

    monkeypatch.setattr(dp, "AkshareSectorProvider", _BrokenAkshare)

    sample_payload = {
        "data": {"diff": {"0": {"f3": 100, "f12": "BK0001", "f14": "测试板块",
                                  "f128": "龙头A", "f140": "000001", "f141": 200, "f105": 5}}}
    }
    monkeypatch.setattr(
        "app.data_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            json=lambda: sample_payload,
            raise_for_status=lambda: None,
            text=str(sample_payload),
        ),
    )

    provider = LiveSectorProvider()
    sectors = provider.sectors()
    assert len(sectors) == 1
    assert sectors[0].code == "BK0001"
    assert sectors[0].pct_change == 1.0
    assert provider.source_name == "EastMoney sectors (push2delay) · 成员映射 1/1"


def test_live_sector_provider_raises_when_both_sources_fail(monkeypatch) -> None:
    """akShare 和 EM 都失败时，LiveSectorProvider 必须抛错而不是静默返回空。"""
    import app.data_provider as dp

    class _BrokenAkshare:
        source_name = "broken-akshare"
        def sectors(self): raise RuntimeError("a")
        def sector_for_code(self, code): raise RuntimeError("a")

    class _BrokenEM:
        source_name = "broken-em"
        def sectors(self): raise RuntimeError("b")
        def sector_for_code(self, code): raise RuntimeError("b")

    monkeypatch.setattr(dp, "AkshareSectorProvider", _BrokenAkshare)
    monkeypatch.setattr(dp, "EastMoneySectorProvider", _BrokenEM)

    provider = LiveSectorProvider()
    with pytest.raises(RuntimeError, match="所有实时板块源均不可用"):
        provider.sectors()


def test_east_money_sector_provider_rejects_an_unusable_member_mapping(monkeypatch) -> None:
    """板块列表可读但成员列表全失败时，不能把 P1/P4 伪装成正常的零候选。"""
    list_payload = {
        "data": {"diff": {
            "0": {"f3": 100, "f12": "BK0001", "f14": "测试板块", "f128": "龙头", "f140": "000001", "f141": 200},
        }}
    }

    def get(_url, *, params, **_kwargs):
        if params["fs"] == "m:90+t:2":
            return SimpleNamespace(json=lambda: list_payload, raise_for_status=lambda: None)
        raise ConnectionError("member endpoint unavailable")

    monkeypatch.setattr("app.data_provider.requests.get", get)

    with pytest.raises(RuntimeError, match="成员列表全部失败"):
        EastMoneySectorProvider().sectors()
