"""指标计算（设计文档 §2）。

所有指标接受标量输入，足够支撑 daily_metrics 表聚合。
历史分位相关指标需要 120 个交易日的窗口；冷启动阶段直接用原始值（覆盖率/置信度另行处理）。

公式一览（设计 §2）：
  HotRaw = 0.5·log(p+1) + 0.25·log(r+1) + 0.15·log(u+1) + 0.10·log(v+1)
  HotScore = HotRaw 在过去 120 个交易日的百分位 × 100
  ExtremeSent = 2 × abs(SentScore − 50)
  ConsensusScore = clamp((1 − item_sent_std / 50) × 100, 0, 100)
  PriceExtension = percentile_rank(pct_change_10d, 过去120d 序列) × 100
  CrowdingScore = 0.40·HotScore + 0.25·ExtremeSent + 0.20·ConsensusScore + 0.15·PriceExtension
  HeatMomentum = 当日 HotRaw / 过去 20 日 HotRaw 均值
  CoverageScore = min(100, 50·min(1, n_eff/30) + 50·min(1, u/10))
"""
from __future__ import annotations

import math
from typing import Iterable


def compute_hot_raw(
    post_count: int,
    reply_count: int,
    unique_authors: int,
    views_or_likes: int,
) -> float:
    """HotRaw = 0.5·log(p+1) + 0.25·log(r+1) + 0.15·log(u+1) + 0.10·log(v+1)。"""
    return (
        0.5 * math.log(post_count + 1)
        + 0.25 * math.log(reply_count + 1)
        + 0.15 * math.log(unique_authors + 1)
        + 0.10 * math.log(views_or_likes + 1)
    )


def percentile_rank(value: float, history: Iterable[float]) -> float:
    """百分位（0..1）。history 为空返回 0.5。"""
    hist = [h for h in history if h is not None]
    if not hist:
        return 0.5
    below_or_equal = sum(1 for h in hist if h <= value)
    return below_or_equal / len(hist)


def compute_hot_score(hot_raw_today: float, history_120d_hot_raw: list[float]) -> float:
    """过去 120 个交易日百分位 × 100。"""
    return percentile_rank(hot_raw_today, history_120d_hot_raw) * 100


def sent_raw_to_score(sent_raw: float) -> float:
    """SentRaw ∈ [-1, 1] → SentScore ∈ [0, 100]，公式 SentScore = 50 + 50·SentRaw。"""
    sent_raw = max(-1.0, min(1.0, sent_raw))
    return 50.0 + 50.0 * sent_raw


def compute_extreme_sent(sent_score_0_100: float) -> float:
    """ExtremeSent = 2 × abs(SentScore − 50)，范围 0..100。"""
    return min(100.0, 2.0 * abs(sent_score_0_100 - 50.0))


def compute_consensus_score(item_sent_std: float) -> float:
    """ConsensusScore = clamp((1 − item_sent_std/50) × 100, 0, 100)。

    设计 §2.3：item_sent_std 使用帖子/回复级别的单条情绪分数标准差。
    """
    raw = (1 - item_sent_std / 50.0) * 100
    return max(0.0, min(100.0, raw))


def compute_price_extension(
    pct_change_10d: float | None,
    history_120d_pct_change_10d: list[float],
    sent_score_0_100: float,
) -> float:
    """根据 SentScore ≥ 50 取上涨分位，否则取 −pct_change_10d 的下跌分位，再 × 100。

    设计 §2.3：必须随情绪方向变化，否则恐慌时会反向误判。
    """
    if pct_change_10d is None or not history_120d_pct_change_10d:
        return 50.0
    if sent_score_0_100 >= 50:
        return percentile_rank(pct_change_10d, history_120d_pct_change_10d) * 100
    else:
        negated = [-p for p in history_120d_pct_change_10d]
        return percentile_rank(-pct_change_10d, negated) * 100


def compute_crowding_score(
    hot_score: float,
    extreme_sent: float,
    consensus_score: float,
    price_extension: float,
) -> float:
    """0.40·HotScore + 0.25·ExtremeSent + 0.20·ConsensusScore + 0.15·PriceExtension。"""
    return 0.40 * hot_score + 0.25 * extreme_sent + 0.20 * consensus_score + 0.15 * price_extension


def compute_heat_momentum(hot_raw_today: float, history_20d_hot_raw_avg: float) -> float:
    """HeatMomentum = 当日 HotRaw / 过去 20 日 HotRaw 均值。"""
    if history_20d_hot_raw_avg <= 0:
        return 1.0
    return hot_raw_today / history_20d_hot_raw_avg


def compute_coverage_score(effective_item_count: float, unique_authors: int) -> float:
    """CoverageScore = min(100, 50·min(1, n/30) + 50·min(1, u/10))。"""
    return min(100.0, 50.0 * min(1.0, effective_item_count / 30.0) + 50.0 * min(1.0, unique_authors / 10.0))
