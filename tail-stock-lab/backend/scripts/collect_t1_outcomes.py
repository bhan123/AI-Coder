"""Cron-friendly T+1 outcome collection after the morning exit cutoff."""

from __future__ import annotations

import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.repository import StrategyRepository
from app.t1_collector import T1OutcomeCollector


def main() -> int:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.weekday() >= 5 or now.time() < time(10, 31):
        print("skip: collect T+1 outcomes after 10:31 Asia/Shanghai on weekdays")
        return 2
    trades = T1OutcomeCollector(StrategyRepository()).collect_due(now)
    print(f"collected={len(trades)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
