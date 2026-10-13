"""Continuously publish the latest two-minute intraday alert scan.

Only a small set of eligible alerts is persisted.  The full market snapshot is
used in memory for the scan but intentionally not written every two minutes.
"""

from __future__ import annotations

import sys
import time as clock
from collections import deque
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data_provider import LiveSectorProvider, LiveSpotProvider
from app.repository import StrategyRepository
from app.service import StrategyService
from app.strategies.limit_up_ambush import LimitUpAmbushAlertStrategy

SCAN_SECONDS = 120


class AlertSnapshotWindow:
    """Keep a small in-process window of full-market scans for momentum confirmation."""

    def __init__(self, size: int = 3) -> None:
        self.size = size
        self._date = None
        self._batches = deque(maxlen=size)

    def observe(self, snapshots, observed_at: datetime) -> None:
        alert_date = observed_at.date()
        if self._date != alert_date:
            self._date = alert_date
            self._batches.clear()
        self._batches.append({snapshot.code: snapshot for snapshot in snapshots})

    def by_code(self) -> dict[str, list]:
        codes = {code for batch in self._batches for code in batch}
        return {
            code: [batch[code] for batch in self._batches if code in batch]
            for code in codes
        }


class _SnapshotBatchProvider:
    def __init__(self, snapshots, source_name: str) -> None:
        self.snapshots = snapshots
        self.source_name = source_name

    def fetch(self, _observed_at):
        return self.snapshots


def _is_tracking_window(observed_at: datetime) -> bool:
    local = observed_at.astimezone(ZoneInfo("Asia/Shanghai")) if observed_at.tzinfo else observed_at
    if local.weekday() >= 5:
        return False
    now = local.time()
    return time(9, 35) <= now <= time(11, 30) or time(13, 0) <= now <= time(15, 0)


def run_once(
    *,
    observed_at: datetime | None = None,
    repository: StrategyRepository | None = None,
    live: LiveSpotProvider | None = None,
    sectors: LiveSectorProvider | None = None,
    snapshots=None,
    recent_snapshots=None,
):
    observed_at = observed_at or datetime.now(ZoneInfo("Asia/Shanghai"))
    strategy = LimitUpAmbushAlertStrategy()
    if not strategy.is_executable_at(observed_at):
        return None
    repository = repository or StrategyRepository()
    live = live or LiveSpotProvider()
    sectors = sectors or LiveSectorProvider()
    service = StrategyService(strategy, repository, sectors=sectors)
    provider = _SnapshotBatchProvider(snapshots, live.source_name) if snapshots is not None else live
    run = service.run(
        provider,
        mode="live",
        observed_at=observed_at,
        capture_origin="scheduled",
        persist_snapshots=False,
        recent_snapshots=recent_snapshots,
    )
    repository.record_alert_run(run)
    return run


def run_cycle(
    *,
    observed_at: datetime | None = None,
    repository: StrategyRepository | None = None,
    live: LiveSpotProvider | None = None,
    sectors: LiveSectorProvider | None = None,
    snapshot_window: AlertSnapshotWindow | None = None,
):
    """Run a new alert scan or continue tracking today's prior alerts."""
    observed_at = observed_at or datetime.now(ZoneInfo("Asia/Shanghai"))
    repository = repository or StrategyRepository()
    live = live or LiveSpotProvider()
    strategy = LimitUpAmbushAlertStrategy()
    alert_date = observed_at.date().isoformat()
    should_scan = strategy.is_executable_at(observed_at)
    should_track = (
        _is_tracking_window(observed_at)
        and repository.has_alert_events(strategy.strategy_id, alert_date)
    )
    if not should_scan and not should_track:
        return None

    snapshots = live.fetch(observed_at)
    snapshot_window = snapshot_window or AlertSnapshotWindow()
    snapshot_window.observe(snapshots, observed_at)
    run = None
    if should_scan:
        run = run_once(
            observed_at=observed_at,
            repository=repository,
            live=live,
            sectors=sectors,
            snapshots=snapshots,
            recent_snapshots=snapshot_window.by_code(),
        )
    finalize = observed_at.time() >= time(14, 57)
    tracked_count = repository.update_alert_outcomes(
        strategy.strategy_id,
        observed_at,
        snapshots,
        finalize=finalize,
    )
    return {"run": run, "tracked_count": tracked_count, "finalized": finalize}


def main() -> int:
    # Reuse the sector provider for the process lifetime so its membership map
    # is cached; live quotes still refresh every scan.
    repository = StrategyRepository()
    live = LiveSpotProvider()
    sectors = LiveSectorProvider()
    snapshot_window = AlertSnapshotWindow()
    while True:
        try:
            cycle = run_cycle(
                repository=repository, live=live, sectors=sectors,
                snapshot_window=snapshot_window,
            )
            if cycle is None:
                print("skip: outside intraday alert windows", flush=True)
            else:
                run = cycle["run"]
                print(
                    f"alert-cycle run={run.run_id if run else '-'} "
                    f"source={run.data_source if run else live.source_name} "
                    f"universe={run.universe_size if run else '-'} "
                    f"alerts={len(run.signals) if run else 0} "
                    f"tracked={cycle['tracked_count']} finalized={cycle['finalized']}",
                    flush=True,
                )
        except Exception as exc:
            # A source outage is visible in journal logs but the next scan is
            # still attempted; it must never affect the tail snapshot timers.
            print(f"alert-scan failed error={exc}", file=sys.stderr, flush=True)
        clock.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
