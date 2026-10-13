"""P2：趋势股缩量回踩 + 尾盘站回均价线。

判定要点：
  1. 收盘价站上 5/10/20 日均线，且均线呈多头排列；
  2. 最近 2–4 日成交量低于近 10 日均量（缩量回踩）；
  3. 尾盘 14:30–15:00 价格在午后平台上沿之上；
  4. 平台高低差小于阈值（横盘而非破位）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models import (
    FactorContribution,
    MarketContext,
    MarketSnapshot,
    PriorityTag,
    Signal,
)
from app.strategies._factors import (
    apply_overrides,
    avg_daily_volume,
    avg_volume,
    close_above_vwap_in_window,
    clip,
    config_to_dict,
    moving_averages,
    rebound_pct,
    relative_strength,
    round2,
)
from app.strategies.base import Strategy


@dataclass(frozen=True)
class P2Config:
    require_ma_alignment: bool = True
    pullback_volume_ratio: float = 0.8
    afternoon_platform_window: int = 30
    platform_band_pct: float = 2.5
    min_score: float = 60.0


class TrendPullbackStrategy(Strategy):
    strategy_id = "p2-trend-pullback"
    version = "1.1.0"
    name = "P2 趋势缩量回踩"
    requires_sectors = False
    max_enrichment_candidates = 80

    def __init__(self, config: P2Config | None = None) -> None:
        self.config = config or P2Config()

    def current_config(self) -> dict:
        return config_to_dict(self.config)

    def with_overrides(self, overrides: dict) -> "TrendPullbackStrategy":
        return TrendPullbackStrategy(apply_overrides(self.config, overrides))

    def should_enrich_context(self, context: MarketContext) -> bool:
        snap = context.snapshot
        return (
            -5.0 <= snap.pct_change <= 2.0
            and snap.turnover_rate >= 1.5
            and 0.4 <= snap.volume_ratio <= 2.5
        )

    def enrichment_priority(self, context: MarketContext) -> float:
        snap = context.snapshot
        return snap.turnover_rate * 2 - abs(snap.pct_change + 2.0)

    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        return self.evaluate_context(MarketContext(snapshot=snapshot))

    def evaluate_context(self, context: MarketContext) -> Signal:
        snap = context.snapshot
        history = context.daily_history

        if len(history) < 20:
            return self._missing_signal(snap, "历史日线不足 20 根，无法计算均线")

        ma = moving_averages(history)
        if not ma.is_valid:
            return self._missing_signal(snap, "5/10/20 日均线缺失")

        aligned = ma.ma5 >= ma.ma10 >= ma.ma20
        above_ma = snap.price >= ma.ma5

        recent_2_4_volume = avg_daily_volume(history, window=3, exclude_last=False)
        baseline_volume = avg_daily_volume(history, window=10, exclude_last=False)
        pullback_ratio = (
            recent_2_4_volume / baseline_volume
            if recent_2_4_volume is not None and baseline_volume not in (None, 0)
            else None
        )
        pullback_shrinking = (
            pullback_ratio is not None and pullback_ratio < self.config.pullback_volume_ratio
        )

        bars = context.intraday_bars
        afternoon_platform: Optional[tuple[float, float]] = None
        afternoon_avg_price: Optional[float] = None
        if bars:
            window_bars = [bar for bar in bars
                           if 150 <= bar.minutes_after_open <= 210]
            if window_bars:
                afternoon_platform = (
                    min(bar.price for bar in window_bars),
                    max(bar.price for bar in window_bars),
                )
                afternoon_avg_price = sum(bar.price for bar in window_bars) / len(window_bars)

        platform_band = None
        if afternoon_platform:
            lo, hi = afternoon_platform
            if lo > 0:
                platform_band = (hi - lo) / lo * 100

        vwap_hold = close_above_vwap_in_window(bars, start_minute=210, end_minute=240) if bars else None

        rebound = rebound_pct(snap)
        rel = relative_strength(snap)

        factors = [
            FactorContribution(
                key="ma5_distance",
                label="收盘相对 MA5",
                value=round2((snap.price - ma.ma5) / ma.ma5 * 100) if ma.ma5 else 0.0,
                score=round(clip(((snap.price - ma.ma5) / ma.ma5 * 100 + 1) / 4 * 18, 0, 18), 1),
                description="收盘价站上 5 日均线越多越强",
            ),
            FactorContribution(
                key="ma_alignment",
                label="均线多头排列",
                value=int(bool(aligned)),
                score=18.0 if aligned else 0.0,
                description="5/10/20 日均线呈现 MA5 ≥ MA10 ≥ MA20",
            ),
            FactorContribution(
                key="pullback_volume",
                label="近 3 日量能 / 10 日均量",
                value=round2(pullback_ratio * 100) if pullback_ratio is not None else 0.0,
                score=round(_score_pullback(pullback_ratio, self.config), 1),
                description="最近 3 日成交是否明显低于 10 日均量",
            ),
            FactorContribution(
                key="platform_band",
                label="午后平台振幅",
                value=round2(platform_band) if platform_band is not None else 0.0,
                score=round(_score_platform_band(platform_band, self.config), 1),
                description="13:30–14:30 平台的高低差比例，越小越说明横盘整理",
            ),
            FactorContribution(
                key="vwap_hold_ratio",
                label="尾盘站上均价线占比",
                value=round2(vwap_hold) if vwap_hold is not None else 0.0,
                score=round(_score_vwap(vwap_hold), 1),
                description="14:30–15:00 价格站上分时均价的占比",
            ),
            FactorContribution(
                key="rebound",
                label="低点回升",
                value=round2(rebound),
                score=round(clip(rebound / 2.5 * 12, 0, 12), 1),
                description="日内低点回升幅度",
            ),
            FactorContribution(
                key="relative_strength",
                label="相对强度",
                value=round2(rel),
                score=round(clip((rel + 0.5) / 2.5 * 10, 0, 10), 1),
                description="相对上证综指的强弱",
            ),
        ]

        score = sum(item.score for item in factors)
        eligible = (
            aligned
            and above_ma
            and pullback_shrinking
            and platform_band is not None
            and platform_band <= self.config.platform_band_pct
            and vwap_hold is not None
            and vwap_hold >= 55.0
            and score >= self.config.min_score
        )

        reasons: list[str] = []
        if not aligned:
            reasons.append("均线未呈多头排列")
        if not above_ma:
            reasons.append(f"收盘价 {snap.price} 低于 MA5 {ma.ma5:.2f}")
        if pullback_ratio is None:
            reasons.append("缺少近期量能数据")
        elif not pullback_shrinking:
            reasons.append(f"近 3 日量能/10 日均量 {pullback_ratio:.2f} ≥ {self.config.pullback_volume_ratio}")
        if platform_band is None or platform_band > self.config.platform_band_pct:
            reasons.append("午后平台振幅超出阈值，未形成横盘")
        if vwap_hold is None or vwap_hold < 55.0:
            reasons.append("尾盘未持续站上分时均价线")
        reason = "；".join(reasons) or (
            f"均线多头排列，午后平台振幅 {platform_band:.2f}%，"
            f"近 3 日量能/10 日均量 {pullback_ratio:.2f}，尾盘均价线支撑"
        )

        risk_level = "high" if snap.pct_change <= -6.0 else "medium" if snap.pct_change <= -4.0 else "low"

        return Signal(
            code=snap.code,
            name=snap.name,
            score=round(score, 1),
            eligible=eligible,
            reason=reason,
            risk_level=risk_level,
            snapshot=snap,
            factors=factors,
            priority_tags=self._priority_tags(context, eligible, aligned, pullback_shrinking, platform_band),
        )

    def _missing_signal(self, snap: MarketSnapshot, reason: str) -> Signal:
        return Signal(
            code=snap.code,
            name=snap.name,
            score=0.0,
            eligible=False,
            reason=reason,
            risk_level="low",
            snapshot=snap,
            factors=[],
            priority_tags=[PriorityTag(
                key="trend_pullback",
                label="趋势股缩量回踩 + 尾盘站回均价线",
                priority=2,
                status="missing_data",
                evidence=[reason],
            )],
        )

    def priority_tags(self, context: MarketContext) -> list[PriorityTag]:
        return []

    def _priority_tags(
        self,
        context: MarketContext,
        eligible: bool,
        aligned: bool,
        shrinking: bool,
        platform_band: Optional[float],
    ) -> list[PriorityTag]:
        ma = moving_averages(context.daily_history)
        evidence = []
        if ma.is_valid:
            evidence.append(f"5/10/20 日均线 {ma.ma5:.2f}/{ma.ma10:.2f}/{ma.ma20:.2f}")
        evidence.append("均线多头排列" if aligned else "均线未多头排列")
        evidence.append("近 3 日缩量" if shrinking else "近 3 日未缩量")
        if platform_band is not None:
            evidence.append(f"午后平台振幅 {platform_band:.2f}%")
        status = "matched" if eligible else "partial"
        return [PriorityTag(
            key="trend_pullback",
            label="趋势股缩量回踩 + 尾盘站回均价线",
            priority=2,
            status=status,
            evidence=evidence,
        )]

    def definition(self) -> dict:
        return {
            "id": self.strategy_id,
            "version": self.version,
            "name": self.name,
            "summary": "趋势向上的个股在最近 3 日缩量回踩，并在尾盘形成横盘并站上均价线。",
            "execution_window": "14:30–15:00",
            "risk_rule": "仅研究信号；历史日线不足时直接标记为待验证。",
            "factors": [
                "MA5 距离",
                "均线多头排列",
                "近 3 日量能 / 10 日均量",
                "午后平台振幅",
                "尾盘站上均价线占比",
                "低点回升",
                "相对强度",
            ],
        }


def _score_pullback(ratio: Optional[float], config: P2Config) -> float:
    if ratio is None:
        return 0.0
    return clip((config.pullback_volume_ratio - ratio) / config.pullback_volume_ratio * 16, 0, 16)


def _score_platform_band(value: Optional[float], config: P2Config) -> float:
    if value is None:
        return 0.0
    return clip((config.platform_band_pct - value) / config.platform_band_pct * 14, 0, 14)


def _score_vwap(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    return clip((value - 55) / 45 * 12, 0, 12)
