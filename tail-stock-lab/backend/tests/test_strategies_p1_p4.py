"""P1–P4 策略的真实数据测试。

每个策略都至少覆盖三条路径：
  - 完整数据 → 标签升级为 matched 或给出真实因子；
  - 数据缺失 → 标记 missing_data，但绝不假装有数据；
  - 数据形态不达标 → partial，给出真实证据。
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.data_provider import (
    ContextAssembler,
    SampleHistoryProvider,
    SampleIntradayProvider,
    SampleProvider,
    SampleSectorProvider,
)
from app.models import MarketSnapshot
from app.strategies import (
    FishingV1Strategy,
    LimitUpAmbushAlertStrategy,
    LeaderReconvergenceStrategy,
    PlatformBreakoutStrategy,
    SectorResonancePullbackStrategy,
    TrendPullbackStrategy,
)


def _assemble(captured_at: datetime) -> dict[str, object]:
    snapshots = SampleProvider().fetch(captured_at)
    assembler = ContextAssembler(
        SampleHistoryProvider(),
        SampleIntradayProvider(),
        SampleSectorProvider(),
    )
    contexts = assembler.assemble(snapshots, captured_at)
    return contexts


@pytest.fixture
def contexts() -> dict[str, object]:
    return _assemble(datetime(2026, 7, 31, 14, 50))


def _make_alert_context_ready(context, snapshot):
    snapshot = snapshot.model_copy(update={"market_pct_change": 0.2})
    context.snapshot = snapshot
    context.recent_snapshots = [
        snapshot.model_copy(update={"price": snapshot.price * 0.994, "pct_change": snapshot.pct_change - 0.5}),
        snapshot.model_copy(update={"price": snapshot.price * 0.997, "pct_change": snapshot.pct_change - 0.3}),
        snapshot,
    ]
    context.market_breadth_pct = 55.0
    context.recent_sector_average_pcts = [1.5, 1.7, 2.0]
    return context


# ---------------------------------------------------------------------------
# P1
# ---------------------------------------------------------------------------

def test_p1_real_intraday_data_drives_sector_resonance_label(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001", "name": "联动样例一"}),
        positive_peer.model_copy(update={"code": "605002", "name": "联动样例二"}),
    ])
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    context.intraday_bars[-1] = context.intraday_bars[-1].model_copy(
        update={"price": max(bar.price for bar in context.intraday_bars)}
    )
    sector_signal = strategy.evaluate_context(context)
    assert sector_signal.eligible is True
    status = sector_signal.priority_tags[0].status
    assert status == "matched"
    assert any("板块" in item for item in sector_signal.priority_tags[0].evidence)
    factor_keys = {factor.key for factor in sector_signal.factors}
    assert {"sector_strength", "vwap_hold_ratio", "volume_shrink"}.issubset(factor_keys)


def test_limit_up_ambush_alert_requires_sector_resonance_and_liquid_leadership(contexts) -> None:
    strategy = LimitUpAmbushAlertStrategy()
    context = contexts["002833"]
    template = context.sector_peers[-1]
    _make_alert_context_ready(context, context.snapshot.model_copy(update={
        "pct_change": 7.2, "volume_ratio": 2.4, "turnover_rate": 7.0,
    }))
    context.sector_peers = [
        template.model_copy(update={"code": f"60500{i}", "pct_change": 2.0})
        for i in range(1, 5)
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is True
    assert signal.score >= strategy.config.min_score
    assert {factor.key for factor in signal.factors} >= {"stock_strength", "sector_resonance", "volume_ratio"}


def test_limit_up_ambush_normalizes_price_band_by_board_limit(contexts) -> None:
    strategy = LimitUpAmbushAlertStrategy()
    context = contexts["002833"]
    template = context.sector_peers[-1]
    context.sector_peers = [
        template.model_copy(update={"code": f"60500{i}", "pct_change": 2.0})
        for i in range(1, 5)
    ]
    _make_alert_context_ready(context, context.snapshot.model_copy(update={
        "code": "301999", "pct_change": 7.2, "volume_ratio": 2.4, "turnover_rate": 7.0,
    }))

    too_early = strategy.evaluate_context(context)
    _make_alert_context_ready(context, context.snapshot.model_copy(update={"pct_change": 14.4}))
    normalized_near_limit = strategy.evaluate_context(context)

    assert too_early.eligible is False
    assert normalized_near_limit.eligible is True
    strength = next(factor for factor in normalized_near_limit.factors if factor.key == "stock_strength")
    assert strength.value == 72.0


def test_limit_up_ambush_requires_three_strengthening_snapshots(contexts) -> None:
    strategy = LimitUpAmbushAlertStrategy()
    context = contexts["002833"]
    template = context.sector_peers[-1]
    context.sector_peers = [
        template.model_copy(update={"code": f"60500{i}", "pct_change": 2.0})
        for i in range(1, 5)
    ]
    current = context.snapshot.model_copy(update={
        "pct_change": 7.2, "volume_ratio": 2.4, "turnover_rate": 7.0,
        "market_pct_change": 0.2,
    })
    context.snapshot = current
    context.recent_snapshots = [
        current.model_copy(update={"price": 16.30, "pct_change": 7.6}),
        current.model_copy(update={"price": 16.27, "pct_change": 7.4}),
        current,
    ]
    context.market_breadth_pct = 55.0
    context.recent_sector_average_pcts = [1.5, 1.7, 2.0]

    fading = strategy.evaluate_context(context)
    context.recent_snapshots = [
        current.model_copy(update={"price": 16.10, "pct_change": 6.7}),
        current.model_copy(update={"price": 16.18, "pct_change": 6.9}),
        current,
    ]
    strengthening = strategy.evaluate_context(context)

    assert fading.eligible is False
    assert strengthening.eligible is True
    momentum = next(factor for factor in strengthening.factors if factor.key == "price_momentum")
    assert momentum.value == 0.5


def test_limit_up_ambush_pauses_when_broad_market_is_retreating(contexts) -> None:
    strategy = LimitUpAmbushAlertStrategy()
    context = contexts["002833"]
    template = context.sector_peers[-1]
    context.sector_peers = [
        template.model_copy(update={"code": f"60500{i}", "pct_change": 2.0})
        for i in range(1, 5)
    ]
    current = context.snapshot.model_copy(update={
        "pct_change": 7.2, "volume_ratio": 2.4, "turnover_rate": 7.0,
        "market_pct_change": -1.2,
    })
    context.snapshot = current
    context.recent_snapshots = [
        current.model_copy(update={"price": 16.10, "pct_change": 6.7}),
        current.model_copy(update={"price": 16.18, "pct_change": 6.9}),
        current,
    ]
    context.market_breadth_pct = 28.0
    context.recent_sector_average_pcts = [1.5, 1.7, 2.0]

    retreating = strategy.evaluate_context(context)
    context.snapshot = current.model_copy(update={"market_pct_change": 0.2})
    context.recent_snapshots[-1] = context.snapshot
    context.market_breadth_pct = 55.0
    healthy = strategy.evaluate_context(context)

    assert retreating.eligible is False
    assert healthy.eligible is True
    regime = next(factor for factor in healthy.factors if factor.key == "market_regime")
    assert regime.value == 55.0


def test_limit_up_ambush_pauses_when_sector_is_retreating(contexts) -> None:
    strategy = LimitUpAmbushAlertStrategy()
    context = contexts["002833"]
    template = context.sector_peers[-1]
    context.sector_peers = [
        template.model_copy(update={"code": f"60500{i}", "pct_change": 2.0})
        for i in range(1, 5)
    ]
    current = context.snapshot.model_copy(update={
        "pct_change": 7.2, "volume_ratio": 2.4, "turnover_rate": 7.0,
        "market_pct_change": 0.2,
    })
    context.snapshot = current
    context.recent_snapshots = [
        current.model_copy(update={"price": 16.10, "pct_change": 6.7}),
        current.model_copy(update={"price": 16.18, "pct_change": 6.9}),
        current,
    ]
    context.market_breadth_pct = 55.0
    context.recent_sector_average_pcts = [2.2, 2.0, 1.8]

    retreating = strategy.evaluate_context(context)
    context.recent_sector_average_pcts = [1.5, 1.7, 2.0]
    strengthening = strategy.evaluate_context(context)

    assert retreating.eligible is False
    assert strengthening.eligible is True
    sector_momentum = next(factor for factor in strengthening.factors if factor.key == "sector_momentum")
    assert sector_momentum.value == 0.5


def test_limit_up_ambush_alert_does_not_alert_for_isolated_surge(contexts) -> None:
    strategy = LimitUpAmbushAlertStrategy()
    context = contexts["002833"]
    context.snapshot = context.snapshot.model_copy(update={
        "pct_change": 7.2, "volume_ratio": 2.4, "turnover_rate": 7.0,
    })
    context.sector_peers = []

    assert strategy.evaluate_context(context).eligible is False


def test_p1_without_sector_data_honest_missing_label(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    from app.models import MarketContext
    bare_snapshot = MarketSnapshot(
        code="999999",
        name="无板块样例",
        price=10.0,
        pct_change=-3.0,
        day_low=9.8,
        turnover_rate=2.0,
        volume_ratio=1.0,
        market_pct_change=-1.0,
        captured_at=datetime(2026, 7, 31, 14, 50),
    )
    signal = strategy.evaluate_context(MarketContext(snapshot=bare_snapshot))
    assert signal.eligible is False
    assert signal.priority_tags[0].status == "missing_data"
    assert signal.priority_tags[0].evidence


def test_p1_rejects_isolated_stock_even_when_it_ranks_first_within_sector(contexts) -> None:
    """个股排名不能被当成板块共振家数；单股独舞必须被排除。"""
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    context.sector_peers = []
    context.sector_rank = 1
    context.sector_total = 50

    signal = strategy.evaluate_context(context)

    resonance = next(factor for factor in signal.factors if factor.key == "sector_resonance")
    assert resonance.value == 0
    assert signal.eligible is False
    assert "同步上涨仅 0 只" in signal.reason


def test_p1_default_requires_at_least_three_rising_sector_members(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers = [
        positive_peer,
        positive_peer.model_copy(update={"code": "605001", "name": "板块联动样例"}),
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "同步上涨仅 2 只" in signal.reason


def test_p1_resonance_score_uses_member_count_not_number_of_sectors(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    context.sector_peers = [
        peer for peer in context.sector_peers if peer.pct_change > 0
    ][:3]
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    context.sector_rank = 1
    context.sector_total = 100

    signal = strategy.evaluate_context(context)

    resonance = next(factor for factor in signal.factors if factor.key == "sector_resonance")
    assert resonance.value == 3
    assert resonance.score > 0


def test_context_uses_sector_strength_rank_not_stock_rank_within_sector(contexts) -> None:
    context = contexts["002833"]

    assert context.sector.code == "BK0001"
    assert context.sector_rank == 1
    assert context.sector_total == 3


def test_v1_priority_evidence_keeps_sector_member_denominator(contexts) -> None:
    signal = FishingV1Strategy().evaluate_context(contexts["002833"])
    p1_tag = next(
        tag for tag in signal.priority_tags if tag.key == "sector_resonance_pullback"
    )

    assert "同板块同步上涨 4/6" in p1_tag.evidence


def test_p1_rejects_sector_outside_front_thirty_percent(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])
    context.sector_rank = 2
    context.sector_total = 3

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "板块排名 2/3" in signal.reason


def test_p1_requires_stock_to_have_proven_intraday_strength(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])

    signal = strategy.evaluate_context(context)

    assert signal.snapshot.pct_change < 0
    assert signal.eligible is False
    assert "个股涨幅" in signal.reason


def test_p1_requires_stock_to_outperform_its_sector_average(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    peer = next(item for item in context.sector_peers if item.pct_change > 0)
    context.sector_peers = [
        peer.model_copy(update={"code": "605001", "pct_change": 5.0}),
        peer.model_copy(update={"code": "605002", "pct_change": 4.0}),
        peer.model_copy(update={"code": "605003", "pct_change": 3.0}),
    ]
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 1.0})
    context.intraday_bars[-1] = context.intraday_bars[-1].model_copy(
        update={"price": max(bar.price for bar in context.intraday_bars)}
    )

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "弱于板块平均" in signal.reason


def test_p1_rejects_pullback_that_breaks_intraday_vwap(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    context.intraday_bars = [
        bar.model_copy(update={"price": bar.avg_price * 0.99})
        if 190 <= bar.minutes_after_open <= 200 else bar
        for bar in context.intraday_bars
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "跌破均价线" in signal.reason


def test_p1_requires_restrengthening_between_1435_and_1455(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    context.intraday_bars = [
        bar.model_copy(update={"price": 16.2, "avg_price": 16.0})
        if bar.minutes_after_open >= 180 else bar
        for bar in context.intraday_bars
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "14:35–14:55 未重新转强" in signal.reason


def test_p1_measures_volume_across_the_whole_post_1400_pullback(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    context.intraday_bars = [
        bar.model_copy(update={"volume": 100_000})
        if 180 <= bar.minutes_after_open < 195 else bar
        for bar in context.intraday_bars
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "未出现明显缩量回踩" in signal.reason


def test_p1_requires_price_above_vwap_for_most_of_the_day(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    context.intraday_bars = [
        bar.model_copy(update={"price": bar.avg_price * 0.99})
        if bar.minutes_after_open < 180 else bar
        for bar in context.intraday_bars
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "全天站上均价线占比" in signal.reason


def test_p1_requires_latest_price_in_upper_quarter_of_intraday_range(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()
    context = contexts["002833"]
    positive_peer = context.sector_peers[-1]
    context.sector_peers.extend([
        positive_peer.model_copy(update={"code": "605001"}),
        positive_peer.model_copy(update={"code": "605002"}),
    ])
    context.snapshot = context.snapshot.model_copy(update={"pct_change": 3.0})
    intraday_low = min(bar.price for bar in context.intraday_bars)
    context.intraday_bars[-1] = context.intraday_bars[-1].model_copy(
        update={"price": intraday_low + 0.01}
    )

    signal = strategy.evaluate_context(context)

    assert signal.eligible is False
    assert "日内振幅上方四分之一" in signal.reason


def test_sample_data_contains_end_to_end_default_p1_candidate(contexts) -> None:
    strategy = SectorResonancePullbackStrategy()

    eligible_codes = {
        code for code, context in contexts.items()
        if strategy.evaluate_context(context).eligible
    }

    assert "605000" in eligible_codes


def test_p1_service_only_enriches_sector_prefilter_candidates() -> None:
    from app.repository import StrategyRepository
    from app.service import StrategyService

    class CountingHistory(SampleHistoryProvider):
        def __init__(self) -> None:
            self.codes: list[str] = []

        def fetch(self, code, end, *, limit=30):
            self.codes.append(code)
            return super().fetch(code, end, limit=limit)

    class CountingIntraday(SampleIntradayProvider):
        def __init__(self) -> None:
            self.codes: list[str] = []

        def fetch(self, code, captured_at):
            self.codes.append(code)
            return super().fetch(code, captured_at)

    history = CountingHistory()
    intraday = CountingIntraday()
    repository = StrategyRepository(db_path=":memory:")
    repository.save_run = lambda *_, **__: None
    service = StrategyService(
        SectorResonancePullbackStrategy(),
        repository,
        history=history,
        intraday=intraday,
        sectors=SampleSectorProvider(),
    )

    service.run(
        SampleProvider(), mode="sample", observed_at=datetime(2026, 7, 31, 14, 50)
    )

    assert history.codes == []
    assert set(intraday.codes) == {"605000", "605001", "605002"}


def test_p1_sample_run_replays_tail_window_even_when_requested_in_morning() -> None:
    from app.repository import StrategyRepository
    from app.service import StrategyService

    repository = StrategyRepository(db_path=":memory:")
    repository.save_run = lambda *_, **__: None
    service = StrategyService(
        SectorResonancePullbackStrategy(),
        repository,
        history=SampleHistoryProvider(),
        intraday=SampleIntradayProvider(),
        sectors=SampleSectorProvider(),
    )

    run = service.run(
        SampleProvider(), mode="sample", observed_at=datetime(2026, 7, 31, 10, 0)
    )

    assert [signal.code for signal in run.signals] == ["605000"]
    assert run.observed_at.hour == 14
    assert run.observed_at.minute == 50


# ---------------------------------------------------------------------------
# P2
# ---------------------------------------------------------------------------

def test_p2_trend_pullback_uses_history_and_intraday(contexts) -> None:
    strategy = TrendPullbackStrategy()
    signal = strategy.evaluate_context(contexts["003010"])
    assert any(factor.key == "ma_alignment" for factor in signal.factors)
    assert any(factor.key == "platform_band" for factor in signal.factors)
    assert signal.eligible is True
    assert signal.priority_tags[0].status == "matched"
    assert signal.priority_tags[0].evidence


def test_p2_reports_missing_data_without_history() -> None:
    strategy = TrendPullbackStrategy()
    snapshot = MarketSnapshot(
        code="888888",
        name="无历史样例",
        price=10.0,
        pct_change=-3.0,
        day_low=9.8,
        turnover_rate=2.0,
        volume_ratio=1.0,
        market_pct_change=-1.0,
        captured_at=datetime(2026, 7, 31, 14, 50),
    )
    from app.models import MarketContext
    context = MarketContext(snapshot=snapshot)
    signal = strategy.evaluate_context(context)
    assert signal.eligible is False
    assert signal.priority_tags[0].status == "missing_data"


def test_p2_p3_p4_bound_live_enrichment_without_dropping_their_sample_candidate(contexts) -> None:
    p2 = TrendPullbackStrategy()
    p3 = PlatformBreakoutStrategy()
    p4 = LeaderReconvergenceStrategy()

    assert p2.max_enrichment_candidates == 80
    assert p2.should_enrich_context(contexts["003010"]) is True
    assert p2.should_enrich_context(contexts["000859"]) is False

    assert p3.max_enrichment_candidates == 80
    assert p3.should_enrich_context(contexts["600872"]) is True
    assert p3.should_enrich_context(contexts["002833"]) is False

    assert p4.requires_history is False
    assert p4.max_enrichment_candidates == 60
    assert p4.should_enrich_context(contexts["000859"]) is True
    assert p4.should_enrich_context(contexts["600872"]) is False


# ---------------------------------------------------------------------------
# P3
# ---------------------------------------------------------------------------

def test_p3_confirms_a_current_intraday_breakout_above_the_prior_platform(contexts) -> None:
    strategy = PlatformBreakoutStrategy()
    signal = strategy.evaluate_context(contexts["600872"])
    factor_keys = {factor.key for factor in signal.factors}
    assert {"platform_range", "breakout_hold_minutes", "volume_multiple", "upper_shadow"}.issubset(factor_keys)
    assert signal.eligible is True
    assert signal.priority_tags[0].status == "matched"
    assert signal.priority_tags[0].evidence


def test_p3_reports_missing_when_intraday_unavailable(contexts) -> None:
    strategy = PlatformBreakoutStrategy()
    contexts["002833"].intraday_bars = []
    signal = strategy.evaluate_context(contexts["002833"])
    assert signal.eligible is False
    assert signal.priority_tags[0].status == "missing_data"
    assert "分时" in signal.priority_tags[0].evidence[0]


# ---------------------------------------------------------------------------
# P4
# ---------------------------------------------------------------------------

def test_p4_leader_signal_uses_sector_and_intraday(contexts) -> None:
    strategy = LeaderReconvergenceStrategy()
    leader_signal = strategy.evaluate_context(contexts["000859"])
    factor_keys = {factor.key for factor in leader_signal.factors}
    assert {"is_leader", "limit_up_status", "seal_trend", "sector_vs_market"}.issubset(factor_keys)
    assert leader_signal.priority_tags[0].status in {"matched", "partial"}
    assert leader_signal.priority_tags[0].evidence
    if leader_signal.eligible:
        assert "仅触及涨停但未封板" not in leader_signal.reason


def test_p4_uses_stock_rank_within_sector_when_provider_has_no_leader_code(contexts) -> None:
    """行业榜只给领涨名称时，P4 仍应按同板块个股涨幅识别龙头。"""
    strategy = LeaderReconvergenceStrategy()
    context = contexts["000859"]
    context.sector = context.sector.model_copy(update={"leader_code": None})
    context.sector_rank = 30
    context.sector_peers = [
        context.snapshot.model_copy(update={"code": "000860", "pct_change": 6.0}),
        context.snapshot.model_copy(update={"code": "000861", "pct_change": 4.0}),
    ]
    context.intraday_bars = [
        bar.model_copy(update={"price": 5.56}) if index >= len(context.intraday_bars) - 30 else bar
        for index, bar in enumerate(context.intraday_bars)
    ]

    signal = strategy.evaluate_context(context)

    assert signal.eligible is True
    assert any(factor.key == "stock_rank" and factor.value == 1 for factor in signal.factors)


def test_p4_rejects_isolated_limit_up_without_sector_support(contexts) -> None:
    strategy = LeaderReconvergenceStrategy()
    contexts["600872"].sector = None
    contexts["600872"].sector_peers = []
    signal = strategy.evaluate_context(contexts["600872"])
    assert signal.eligible is False
    assert signal.priority_tags[0].status == "missing_data"


# ---------------------------------------------------------------------------
# 服务端串联：保证 V1 + P1–P4 都能落库
# ---------------------------------------------------------------------------

def test_service_runs_all_strategies_against_same_context() -> None:
    import os
    import tempfile
    from app.repository import StrategyRepository
    from app.service import StrategyService
    from app.strategies import ALL_STRATEGIES

    db_file = tempfile.NamedTemporaryFile(
        prefix="tail-stock-lab-test-",
        suffix=".db",
        dir=os.path.dirname(__file__),
        delete=False,
    )
    db_file.close()
    try:
        repository = StrategyRepository(db_path=db_file.name)
        services = {
            sid: StrategyService(cls(), repository) for sid, cls in ALL_STRATEGIES.items()
        }

        observed_at = datetime(2026, 7, 31, 14, 50)
        runs = {}
        for sid, service in services.items():
            runs[sid] = service.run(SampleProvider(), mode="sample", observed_at=observed_at)

        assert len(runs) == len(ALL_STRATEGIES)
        for sid, run in runs.items():
            assert run.strategy_id == sid
            # 哪怕没有 candidate，universe 必须存档，否则回测拿不到截面。
            assert run.universe_size == len(SampleProvider().fetch(observed_at))
    finally:
        try:
            os.unlink(db_file.name)
        except OSError:
            pass


def test_history_provider_returns_deterministic_sample() -> None:
    provider = SampleHistoryProvider()
    today = date(2026, 7, 31)
    bars = provider.fetch("002833", today, limit=20)
    assert len(bars) == 20
    again = provider.fetch("002833", today, limit=20)
    assert [bar.close for bar in bars] == [bar.close for bar in again]


# ---------------------------------------------------------------------------
# V1 v1.1.0 真实数据修复（ISSUE-3，2026-08-06）
# 在腾讯+新浪聚合源下，14:50 截面里绝大多数下跌票 day_low==price（回升还没发生），
# 而且个股弱于指数 2~7% 是常态。原 v1.0.0 的 0.7% 回升 + -0.3% 相对强度两道硬门槛
# 跟数据特征结构性互斥。下面这套测试断言 v1.1.0 在修复后仍按"设计意图"工作。
# ---------------------------------------------------------------------------


def _v1_snapshot(
    *,
    pct_change: float,
    rebound: float,
    relative_strength: float,
    turnover: float = 5.0,
    volume_ratio: float = 1.2,
    market_pct_change: float = 0.5,
) -> MarketSnapshot:
    """构造一张价格 / 最低价让 rebound ≈ 期望值的快照。"""
    price = 10.0
    day_low = price / (1 + rebound / 100) if rebound else price
    return MarketSnapshot(
        code="000001",
        name="test",
        price=price,
        pct_change=pct_change,
        day_low=day_low,
        turnover_rate=turnover,
        volume_ratio=volume_ratio,
        market_pct_change=market_pct_change,
        captured_at=datetime(2026, 8, 6, 14, 50),
    )


def test_v1_110_admits_a_boundary_pullback_candidate() -> None:
    """修复后，边界票（pct=-2.17 / rebound=5.13 / relstr=-2.62）应被选中。

    在 08-06 真实截面上 301382 / 300234 就是这种形态，score 落在 62~65。
    """
    strategy = FishingV1Strategy()
    snapshot = _v1_snapshot(
        pct_change=-2.17,
        rebound=5.13,
        relative_strength=-2.62,
        turnover=12.29,
        volume_ratio=1.30,
        market_pct_change=0.45,
    )
    signal = strategy.evaluate(snapshot)
    assert signal.eligible, f"expected eligible, got score={signal.score} reason={signal.reason}"
    assert 60 <= signal.score <= 70
    assert signal.risk_level == "low"


def test_v1_110_rejects_names_outside_decline_band() -> None:
    """修复只放宽"回升"和"相对强度"，不改变"日内必须下跌 2~7%"的硬约束。"""
    strategy = FishingV1Strategy()
    # 涨幅 +5% 的票：设计意图是排除，不应入选
    snapshot = _v1_snapshot(
        pct_change=+5.0,
        rebound=10.0,
        relative_strength=+4.5,
        turnover=15.0,
        volume_ratio=2.0,
        market_pct_change=0.5,
    )
    assert strategy.evaluate(snapshot).eligible is False


def test_v1_110_keeps_relstr_below_minus_three_rejected() -> None:
    """相对强度门现在是 ≥ -3.0（不是 -0.3），但 -4.0 仍应被拒。"""
    strategy = FishingV1Strategy()
    snapshot = _v1_snapshot(
        pct_change=-3.0,
        rebound=2.0,
        relative_strength=-4.0,
        turnover=8.0,
        volume_ratio=1.5,
        market_pct_change=1.0,
    )
    assert strategy.evaluate(snapshot).eligible is False


def test_v1_110_keeps_rebound_below_floor_rejected() -> None:
    """回升门现在是 ≥ 0.3%（不是 0.7%），但 0.0% 仍应被拒。"""
    strategy = FishingV1Strategy()
    snapshot = _v1_snapshot(
        pct_change=-3.0,
        rebound=0.0,
        relative_strength=-1.0,
        turnover=8.0,
        volume_ratio=1.5,
        market_pct_change=0.5,
    )
    assert strategy.evaluate(snapshot).eligible is False


def test_v1_config_defaults_match_documented_v110() -> None:
    """dataclass 默认值是修复的契约，UI 调参面板依赖它，禁止悄悄改回去。"""
    cfg = FishingV1Strategy().config
    assert cfg.min_rebound_pct == 0.3
    assert cfg.min_relative_strength == -3.0
    assert cfg.min_score == 62.0
