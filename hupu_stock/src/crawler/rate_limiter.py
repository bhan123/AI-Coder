"""保守限速器。

设计文档 §9.3：单次抓取 < 200 个帖子，sleep 间隔 ≥ 3 秒。
本模块需被 HupuCrawler 在每次外部请求前调用，避免触发虎扑访问限制。
"""
from __future__ import annotations

import random
import time


class RateLimiter:
    def __init__(self, min_interval: float = 3.0, max_interval: float = 5.0) -> None:
        self._min = min_interval
        self._max = max_interval
        self._last = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        sleep_for = random.uniform(self._min, self._max) - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)
        self._last = time.monotonic()

    def __enter__(self) -> "RateLimiter":
        self.wait()
        return self

    def __exit__(self, *exc: object) -> None:
        return None
