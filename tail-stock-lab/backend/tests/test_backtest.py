from datetime import datetime

from app.backtest import ExecutionPolicy, simulate_t1_exit, summarize_backtest
from app.data_provider import SampleProvider
from app.models import MarketSnapshot, NextDayPath, StrategyRun
from app.service import StrategyService
from app.strategies.fishing_v1 import FishingV1Strategy
from app.strategies.limit_up_ambush import LimitUpAmbushAlertStrategy
from app.strategies.platform_breakout_p3 import PlatformBreakoutStrategy
from app.t1_collector import TencentT1PathProvider


def _signal():
    snapshot = MarketSnapshot(
        code="000001", name="样例", price=10, pct_change=-4, day_low=9.8,
        turnover_rate=3, volume_ratio=1.5, market_pct_change=-1, captured_at=datetime(2026, 7, 1, 14, 50),
    )
    return FishingV1Strategy().evaluate(snapshot)


def test_t1_profit_requires_executable_rule_exit_not_just_peak() -> None:
    trade = simulate_t1_exit(
        _signal(),
        NextDayPath(code="000001", entry_price=10, prices=[10.03, 10.20, 10.12], observed_at=datetime.now()),
    )
    assert trade.touched_breakeven is True
    assert trade.profitable_exit is True
    assert trade.exit_reason == "trailing_exit"


def test_t1_trade_records_the_observed_morning_price_range() -> None:
    trade = simulate_t1_exit(
        _signal(),
        NextDayPath(code="000001", entry_price=10, prices=[10.03, 10.20, 10.12], observed_at=datetime.now()),
    )

    assert trade.session_low_price == 10.03
    assert trade.session_high_price == 10.20


def test_stop_loss_records_actual_path_price_and_cost() -> None:
    trade = simulate_t1_exit(
        _signal(),
        NextDayPath(code="000001", entry_price=10, prices=[9.68], observed_at=datetime.now()),
        ExecutionPolicy(round_trip_cost_rate=0.0015, stop_loss_rate=0.03),
    )
    assert trade.exit_reason == "stop_loss"
    assert trade.profitable_exit is False
    assert trade.net_return_pct < -3


def test_summary_reports_breakeven_and_profit_as_separate_metrics() -> None:
    signal = _signal()
    summary = summarize_backtest(
        [signal],
        [NextDayPath(code="000001", entry_price=10, prices=[10.03, 9.7], observed_at=datetime.now())],
        mode="sample",
    )
    assert summary.touched_breakeven_rate == 100
    assert summary.profitable_exit_rate == 0


class _InMemoryRepository:
    def __init__(self) -> None:
        self.run = None
        self.snapshots = []
        self.alert_runs = []
        self.has_events = False
        self.outcome_updates = []

    def save_run(self, run, snapshots=None) -> None:
        self.run = run
        self.snapshots = snapshots or []

    def latest_run(self, _strategy_id):
        return self.run

    def record_alert_run(self, run):
        self.alert_runs.append(run)

    def has_alert_events(self, _strategy_id, _alert_date):
        return self.has_events

    def update_alert_outcomes(self, strategy_id, observed_at, snapshots, *, finalize=False):
        self.outcome_updates.append((strategy_id, observed_at, snapshots, finalize))
        return len(snapshots)


def test_latest_live_run_does_not_return_a_newer_sample_run() -> None:
    import os
    import tempfile
    from app.repository import StrategyRepository

    db_file = tempfile.NamedTemporaryFile(
        prefix="tail-stock-lab-live-only-",
        suffix=".db",
        dir=os.path.dirname(__file__),
        delete=False,
    )
    db_file.close()
    try:
        repository = StrategyRepository(db_path=db_file.name)
        repository.save_run(StrategyRun(
            run_id="live-run", strategy_id="p1-sector-resonance", version="1.1.0",
            observed_at=datetime(2026, 8, 3, 14, 50), mode="live",
            data_source="live", execution_status="tradable", universe_size=1, signals=[],
        ))
        repository.save_run(StrategyRun(
            run_id="sample-run", strategy_id="p1-sector-resonance", version="1.1.0",
            observed_at=datetime(2026, 8, 3, 15, 0), mode="sample",
            data_source="sample", execution_status="sample", universe_size=1, signals=[],
        ))

        latest = repository.latest_live_run("p1-sector-resonance")

        assert latest is not None
        assert latest.run_id == "live-run"
    finally:
        try:
            os.unlink(db_file.name)
        except OSError:
            pass


def test_live_result_is_not_executable_outside_tail_window_and_keeps_source() -> None:
    service = StrategyService(FishingV1Strategy(), _InMemoryRepository())
    run = service.run(
        SampleProvider(),
        mode="live",
        observed_at=datetime(2026, 7, 31, 19, 0),
    )
    assert run.execution_status == "outside_tail_window"
    assert run.signals == []
    assert run.data_source == "内置研究样例"

    persisted = service.repository.latest_run("fishing-reversal")
    assert persisted is not None
    assert persisted.execution_status == "outside_tail_window"
    assert persisted.data_source == "内置研究样例"
    assert len(service.repository.snapshots) == len(
        SampleProvider().fetch(datetime(2026, 7, 31, 19, 0))
    )


def test_intraday_alert_is_executable_during_morning_and_afternoon_alert_windows() -> None:
    strategy = LimitUpAmbushAlertStrategy()

    assert strategy.is_executable_at(datetime(2026, 7, 31, 9, 35)) is True
    assert strategy.is_executable_at(datetime(2026, 7, 31, 10, 31)) is False
    assert strategy.is_executable_at(datetime(2026, 7, 31, 13, 30)) is True
    assert strategy.is_executable_at(datetime(2026, 7, 31, 14, 31)) is False


def test_intraday_alert_scan_persists_only_alerts_not_the_full_market_snapshot() -> None:
    from scripts.scan_limit_up_ambush import run_once

    class Live:
        source_name = "test live"

        def fetch(self, observed_at):
            return SampleProvider().fetch(observed_at)

    class Sectors:
        source_name = "test sectors"

        def sector_for_code(self, code):
            from app.data_provider import SampleSectorProvider
            return SampleSectorProvider().sector_for_code(code)

        def sectors(self):
            from app.data_provider import SampleSectorProvider
            return SampleSectorProvider().sectors()

    repository = _InMemoryRepository()
    run = run_once(
        observed_at=datetime(2026, 7, 31, 9, 35),
        repository=repository,
        live=Live(),
        sectors=Sectors(),
    )

    assert run is not None
    assert run.execution_status == "tradable"
    assert repository.snapshots == []
    assert repository.alert_runs == [run]


def test_intraday_alert_tracker_continues_after_new_alert_window_closes() -> None:
    from scripts.scan_limit_up_ambush import run_cycle

    class Live:
        source_name = "test live"

        def __init__(self):
            self.calls = 0

        def fetch(self, observed_at):
            self.calls += 1
            return SampleProvider().fetch(observed_at)

    repository = _InMemoryRepository()
    repository.has_events = True
    live = Live()

    result = run_cycle(
        observed_at=datetime(2026, 7, 31, 10, 45),
        repository=repository,
        live=live,
    )

    assert result is not None
    assert result["run"] is None
    assert result["tracked_count"] == 9
    assert live.calls == 1
    assert repository.alert_runs == []
    assert repository.outcome_updates[0][1] == datetime(2026, 7, 31, 10, 45)
    assert repository.outcome_updates[0][3] is False


def test_intraday_alert_scan_waits_for_three_strengthening_market_snapshots() -> None:
    from app.data_provider import SampleSectorProvider
    from scripts.scan_limit_up_ambush import AlertSnapshotWindow, run_cycle

    class Live:
        source_name = "test live"

        def __init__(self):
            self.pct = 6.7

        def fetch(self, observed_at):
            rows = [
                ("002833", "候选", 16.10 + (self.pct - 6.7) * 0.2, self.pct, 2.4, 7.0),
                ("605001", "联动一", 11.2, 2.0, 1.2, 4.0),
                ("605002", "联动二", 10.3, 2.0, 1.2, 4.0),
                ("605003", "联动三", 9.8, 2.0, 1.2, 4.0),
            ]
            return [MarketSnapshot(
                code=code, name=name, price=price, pct_change=pct, day_low=price * 0.98,
                volume_ratio=volume, turnover_rate=turnover, market_pct_change=0.2,
                captured_at=observed_at,
            ) for code, name, price, pct, volume, turnover in rows]

    live = Live()
    repository = _InMemoryRepository()
    window = AlertSnapshotWindow(size=3)
    runs = []
    for minute, pct in ((35, 6.7), (37, 6.9), (39, 7.2)):
        live.pct = pct
        runs.append(run_cycle(
            observed_at=datetime(2026, 7, 31, 9, minute), repository=repository,
            live=live, sectors=SampleSectorProvider(), snapshot_window=window,
        )["run"])

    assert runs[0].signals == []
    assert runs[1].signals == []
    assert [signal.code for signal in runs[2].signals] == ["002833"]


def test_intraday_alert_tracker_finalizes_the_day_after_1457() -> None:
    from scripts.scan_limit_up_ambush import run_cycle

    class Live:
        source_name = "test live"

        def fetch(self, observed_at):
            return SampleProvider().fetch(observed_at)

    repository = _InMemoryRepository()
    repository.has_events = True

    result = run_cycle(
        observed_at=datetime(2026, 7, 31, 14, 58),
        repository=repository,
        live=Live(),
    )

    assert result is not None
    assert result["run"] is None
    assert result["finalized"] is True
    assert repository.outcome_updates[0][3] is True


def test_scheduled_capture_includes_all_released_strategies() -> None:
    from scripts.capture_tail_snapshot import scheduled_strategies

    assert [strategy.strategy_id for strategy in scheduled_strategies()] == [
        "fishing-reversal",
        "p1-sector-resonance",
        "p2-trend-pullback",
        "p3-platform-breakout",
        "p4-leader-reconvergence",
    ]


def test_scheduled_capture_gives_each_strategy_only_its_required_live_data() -> None:
    from scripts.capture_tail_snapshot import scheduled_service, scheduled_strategies

    class Provider:
        source_name = "spy"

    history = Provider()
    intraday = Provider()
    sectors = Provider()
    repository = _InMemoryRepository()
    services = {
        strategy.strategy_id: scheduled_service(
            strategy, repository, history=history, intraday=intraday, sectors=sectors
        )
        for strategy in scheduled_strategies()
    }

    assert services["p2-trend-pullback"].assembler.history is history
    assert services["p2-trend-pullback"].assembler.intraday is intraday
    assert services["p2-trend-pullback"].assembler.sectors.source_name == "not required"
    assert services["p3-platform-breakout"].assembler.history is history
    assert services["p4-leader-reconvergence"].assembler.history.source_name == "not required"
    assert services["p4-leader-reconvergence"].assembler.intraday is intraday
    assert services["p4-leader-reconvergence"].assembler.sectors is sectors


def test_run_records_the_required_sector_source() -> None:
    """正式归档必须能看出 P1/P4 实际使用的板块源，而非只显示个股行情源。"""
    class SectorAwareFishing(FishingV1Strategy):
        requires_sectors = True

    class Sectors:
        source_name = "EastMoney sectors · 成员映射 90/90"

        def sector_for_code(self, _code):
            return None

        def sectors(self):
            return []

    service = StrategyService(SectorAwareFishing(), _InMemoryRepository(), sectors=Sectors())

    run = service.run(SampleProvider(), mode="sample", observed_at=datetime(2026, 8, 6, 14, 50))

    assert run.data_source == "内置研究样例 + EastMoney sectors · 成员映射 90/90"


def test_scheduled_capture_continues_after_one_strategy_data_failure(capsys) -> None:
    from scripts.capture_tail_snapshot import capture_batch

    class Strategy:
        def __init__(self, strategy_id: str) -> None:
            self.strategy_id = strategy_id

    completed: list[str] = []

    def run_one(strategy):
        if strategy.strategy_id == "p1-sector-resonance":
            raise RuntimeError("sector source unavailable")
        completed.append(strategy.strategy_id)
        return type("Run", (), {
            "strategy_id": strategy.strategy_id,
            "run_id": f"run-{strategy.strategy_id}",
            "data_source": "live",
            "universe_size": 100,
            "signals": [],
        })()

    failures = capture_batch(
        [Strategy("fishing-reversal"), Strategy("p1-sector-resonance"), Strategy("p2-trend-pullback")],
        run_one,
    )

    assert completed == ["fishing-reversal", "p2-trend-pullback"]
    assert failures == ["p1-sector-resonance"]
    assert "failed strategy=p1-sector-resonance" in capsys.readouterr().err


def test_t1_chart_capture_failure_does_not_block_formal_snapshot(capsys) -> None:
    from scripts.capture_tail_snapshot import collect_t1_market_reviews

    class FailingCollector:
        def __init__(self, repository) -> None:
            assert repository == "repository"

        def collect_due(self, observed_at):
            raise RuntimeError("minute source unavailable")

    collected = collect_t1_market_reviews(
        "repository", datetime(2026, 8, 12, 14, 50), FailingCollector
    )

    assert collected == 0
    assert "failed T+1 market review" in capsys.readouterr().err


def test_live_result_is_executable_in_tail_window() -> None:
    service = StrategyService(FishingV1Strategy(), _InMemoryRepository())
    run = service.run(
        SampleProvider(),
        mode="live",
        observed_at=datetime(2026, 7, 31, 14, 45),
    )
    assert run.execution_status == "tradable"
    assert len(run.signals) == 3


def test_service_applies_strategy_enrichment_cap_before_calling_live_providers() -> None:
    history_calls: list[str] = []
    intraday_calls: list[str] = []

    class HistorySpy:
        source_name = "history spy"

        def fetch(self, code, end, *, limit=30):
            history_calls.append(code)
            return []

    class IntradaySpy:
        source_name = "intraday spy"

        def fetch(self, code, captured_at):
            intraday_calls.append(code)
            return []

    class EmptySectors:
        source_name = "empty sectors"

        def sector_for_code(self, code):
            return None

        def sectors(self):
            return []

    class CappedP3(PlatformBreakoutStrategy):
        max_enrichment_candidates = 2

        def should_enrich_context(self, context):
            return True

        def enrichment_priority(self, context):
            return context.snapshot.turnover_rate

    service = StrategyService(
        CappedP3(),
        _InMemoryRepository(),
        history=HistorySpy(),
        intraday=IntradaySpy(),
        sectors=EmptySectors(),
    )
    service.run(
        SampleProvider(), mode="sample", observed_at=datetime(2026, 7, 31, 14, 50)
    )

    assert history_calls == ["000859", "605000"]
    assert intraday_calls == ["000859", "605000"]


def test_tencent_minute_path_uses_first_future_trading_day_and_morning_window() -> None:
    signal = _signal()
    payload = {
        "data": {
            "sz000001": {
                "data": [
                    {"date": "20260703", "data": ["0930 10.02 1 1", "1030 10.18 1 1", "1031 9.20 1 1"]},
                    {"date": "20260702", "data": ["0930 10.01 1 1", "0931 10.10 1 1", "1100 9.80 1 1"]},
                ]
            }
        }
    }
    path = TencentT1PathProvider.parse_next_path(signal, payload)
    assert path is not None
    assert path.observed_at.date().isoformat() == "2026-07-02"
    assert path.prices == [10.01, 10.1]


def test_tencent_t1_review_keeps_next_day_points_through_tail_snapshot() -> None:
    signal = _signal()
    payload = {
        "data": {
            "sz000001": {
                "data": [
                    {"date": "20260702", "data": [
                        "0929 9.99 1 1", "0930 10.01 1 1", "1030 10.10 1 1",
                        "1450 10.30 1 1", "1451 10.40 1 1",
                    ]},
                ]
            }
        }
    }

    review = TencentT1PathProvider.parse_review(signal, payload)

    assert review is not None
    assert review.open_price == 10.01
    assert review.low_price == 10.01
    assert review.high_price == 10.30
    assert review.last_price == 10.30
    assert [point.time for point in review.points] == ["0930", "1030", "1450"]


def test_signal_exposes_priority_tags_without_overclaiming_missing_data() -> None:
    tags = {tag.key: tag for tag in _signal().priority_tags}
    assert tags["sector_resonance_pullback"].status == "partial"
    assert tags["trend_pullback"].status == "missing_data"
    assert tags["tail_surge_only"].status == "excluded"
