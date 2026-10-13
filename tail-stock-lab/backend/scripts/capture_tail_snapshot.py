"""Cron-friendly tail-session snapshot capture.

Run this script at 14:50 Asia/Shanghai on trading days.  It fails closed outside
the strategy's declared execution window, so a late manual run cannot silently
produce a tradable signal from stale end-of-day data.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_provider import (
    AkshareHistoryProvider,
    AkshareIntradayProvider,
    LiveSectorProvider,
    LiveSpotProvider,
)
from app.repository import StrategyRepository
from app.service import StrategyService
from app.t1_collector import T1ReviewCollector
from app.strategies.fishing_v1 import FishingV1Strategy
from app.strategies.sector_resonance_p1 import SectorResonancePullbackStrategy
from app.strategies.trend_pullback_p2 import TrendPullbackStrategy
from app.strategies.platform_breakout_p3 import PlatformBreakoutStrategy
from app.strategies.leader_reconvergence_p4 import LeaderReconvergenceStrategy


class _SnapshotProvider:
    def __init__(self, snapshots, source_name: str) -> None:
        self.snapshots = snapshots
        self.source_name = source_name

    def fetch(self, captured_at):
        return self.snapshots


class _EmptyHistoryProvider:
    source_name = "not required"

    def fetch(self, code, end, *, limit=30):
        return []


class _EmptyIntradayProvider:
    source_name = "not required"

    def fetch(self, code, captured_at):
        return []


class _EmptySectorProvider:
    source_name = "not required"

    def sector_for_code(self, code):
        return None

    def sectors(self):
        return []


def scheduled_strategies():
    return [
        FishingV1Strategy(),
        SectorResonancePullbackStrategy(),
        TrendPullbackStrategy(),
        PlatformBreakoutStrategy(),
        LeaderReconvergenceStrategy(),
    ]


def scheduled_service(strategy, repository, *, history, intraday, sectors) -> StrategyService:
    """Build the smallest live-data dependency set required by one strategy."""
    if strategy.strategy_id == FishingV1Strategy.strategy_id:
        return StrategyService(
            strategy,
            repository,
            history=_EmptyHistoryProvider(),
            intraday=_EmptyIntradayProvider(),
            sectors=_EmptySectorProvider(),
        )
    return StrategyService(
        strategy,
        repository,
        history=history if strategy.requires_history else _EmptyHistoryProvider(),
        intraday=intraday if strategy.requires_intraday else _EmptyIntradayProvider(),
        sectors=sectors if strategy.requires_sectors else _EmptySectorProvider(),
    )


def capture_batch(strategies, run_one) -> list[str]:
    """Capture every strategy independently so one optional data source cannot stop the batch."""
    failures: list[str] = []
    for strategy in strategies:
        try:
            run = run_one(strategy)
        except Exception as exc:
            failures.append(strategy.strategy_id)
            print(f"failed strategy={strategy.strategy_id} error={exc}", file=sys.stderr)
            continue
        print(
            f"captured strategy={run.strategy_id} run={run.run_id} "
            f"source={run.data_source} universe={run.universe_size} "
            f"signals={len(run.signals)}"
        )
    return failures


def collect_t1_market_reviews(repository, observed_at, collector_class=T1ReviewCollector) -> int:
    """A missing review chart must never block the formal tail snapshot."""
    try:
        return len(collector_class(repository).collect_due(observed_at))
    except Exception as exc:
        print(f"failed T+1 market review error={exc}", file=sys.stderr)
        return 0


def main() -> int:
    observed_at = datetime.now(ZoneInfo("Asia/Shanghai"))
    if not StrategyService._is_tail_window(observed_at):
        print("skip: only capture a tradable snapshot between 14:30 and 15:00 Asia/Shanghai")
        return 2

    live = LiveSpotProvider()
    snapshots = live.fetch(observed_at)
    provider = _SnapshotProvider(snapshots, live.source_name)
    repository = StrategyRepository()
    history = AkshareHistoryProvider()
    intraday = AkshareIntradayProvider()
    sectors = LiveSectorProvider()

    def run_one(strategy):
        service = scheduled_service(
            strategy,
            repository,
            history=history,
            intraday=intraday,
            sectors=sectors,
        )
        return service.run(provider, mode="live", observed_at=observed_at, capture_origin="scheduled")

    failures = capture_batch(scheduled_strategies(), run_one)
    reviewed = collect_t1_market_reviews(repository, observed_at)
    print(f"reviewed_t1_market_charts={reviewed}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
