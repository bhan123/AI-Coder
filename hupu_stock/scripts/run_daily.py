"""手动跑每日分析流水线（设计文档 §6）。"""
from __future__ import annotations

import logging
import sys

from analysis.pipeline import run_daily_pipeline


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    stats = run_daily_pipeline()
    print(f"[run_daily] {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
