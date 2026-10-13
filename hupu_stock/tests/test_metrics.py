"""指标公式测试。

设计文档 §2 给出了全部公式的精确形式。
"""
from __future__ import annotations

import pytest

from analysis.metrics import (
    compute_crowding_score,
    compute_coverage_score,
    compute_extreme_sent,
    compute_heat_momentum,
    compute_hot_raw,
    compute_price_extension,
)

pytestmark = pytest.mark.skip(reason="stub: 待 metrics.* 实现")


def test_hot_raw_formula_exact() -> None:
    # TODO: 已知输入比对 HotRaw = 0.5*log(p+1)+0.25*log(r+1)+0.15*log(u+1)+0.10*log(v+1)
    ...


def test_extreme_sent_symmetric_around_50() -> None:
    # TODO: sent=30 与 sent=70 给出相同 ExtremeSent
    ...


def test_price_extension_direction_follows_sentiment() -> None:
    # TODO: SentScore >= 50 取上涨分位；< 50 取下跌分位
    ...


def test_crowding_score_weights_sum_to_one() -> None:
    # TODO: 0.40 + 0.25 + 0.20 + 0.15 == 1.0
    ...


def test_coverage_score_capped_at_100() -> None:
    # TODO: 高 effective_item_count / unique_authors 不会超过 100
    ...


def test_heat_momentum_baseline_is_one() -> None:
    # TODO: 当日 HotRaw == 历史均值 → 1.0
    ...
