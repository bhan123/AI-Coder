"""P3：平台放量突破 + 尾盘确认。

判定要点：
  1. 最近 20 日（不含今日）形成高点/低点收敛的平台；
  2. 今日最高价突破平台高点；
  3. 收盘/最新价仍站在突破位之上（突破后维持）；
  4. 今日实时量能 ≥ 近 5 日均量 × 1.5；
  5. 上影线长度不能大于实体的 0.5 倍（避免假突破）。
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
    clip,
    config_to_dict,
    platform_range,
    rebound_pct,
    relative_strength,
    round2,
)
from app.strategies.base import Strategy


@dataclass(frozen=True)
class P3Config:
    platform_window: int = 20
    volume_multiple: float = 1.5
    min_volume_ratio: float = 1.2
    max_upper_shadow: float = 0.5
    min_breakout_hold_minutes: int = 15
    min_score: float = 60.0


class PlatformBreakoutStrategy(Strategy):
    strategy_id = "p3-platform-breakout"
    version = "1.1.0"
    name = "P3 平台放量突破"
    requires_sectors = False
    max_enrichment_candidates = 80

    def __init__(self, config: P3Config | None = None) -> None:
        self.config = config or P3Config()

    def current_config(self) -> dict:
        return config_to_dict(self.config)

    def with_overrides(self, overrides: dict) -> "PlatformBreakoutStrategy":
        return PlatformBreakoutStrategy(apply_overrides(self.config, overrides))

    def should_enrich_context(self, context: MarketContext) -> bool:
        snap = context.snapshot
        return (
            1.0 <= snap.pct_change <= 9.8
            and snap.turnover_rate >= 0.8
            and snap.volume_ratio >= self.config.min_volume_ratio
        )

    def enrichment_priority(self, context: MarketContext) -> float:
        snap = context.snapshot
        return snap.pct_change * max(snap.volume_ratio, 1.0) + snap.turnover_rate * 0.1

    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        return self.evaluate_context(MarketContext(snapshot=snapshot))

    def evaluate_context(self, context: MarketContext) -> Signal:
        snap = context.snapshot
        history = context.daily_history
        intraday = context.intraday_bars

        if len(history) < self.config.platform_window:
            return self._missing_signal(snap, f"历史日线不足 {self.config.platform_window} 根，无法识别平台")

        # Daily history is made of completed sessions.  Today's breakout must
        # come from the live minute feed, not from a stale "last" daily bar.
        platform = platform_range(
            history,
            window=self.config.platform_window,
            exclude_last=False,
        )
        if platform is None:
            return self._missing_signal(snap, "平台窗口样本不足，无法形成平台高低点")
        platform_high, platform_low = platform
        platform_range_pct = (platform_high - platform_low) / platform_low * 100 if platform_low else 0.0

        if not intraday:
            return self._missing_signal(snap, "分时数据缺失，无法验证突破后维持时间")

        today_open = intraday[0].price
        today_high = max(bar.price for bar in intraday)
        breakout_high = today_high > platform_high

        first_breakout_minute: Optional[int] = None
        last_minute = intraday[-1].minutes_after_open
        for bar in intraday:
            if bar.price > platform_high:
                first_breakout_minute = bar.minutes_after_open
                break

        hold_minutes = (
            max(0, last_minute - first_breakout_minute)
            if first_breakout_minute is not None
            else 0
        )
        breakout_sustained = hold_minutes >= self.config.min_breakout_hold_minutes
        last_price = intraday[-1].price
        closed_above_breakout = last_price > platform_high

        baseline_volume = avg_daily_volume(history, window=5, exclude_last=False)
        today_volume = sum(bar.volume for bar in intraday)
        volume_ratio = today_volume / baseline_volume if baseline_volume else None
        volume_supported = (
            volume_ratio is not None
            and volume_ratio >= self.config.volume_multiple
        )
        body = abs(last_price - today_open)
        upper_shadow = (
            (today_high - max(today_open, last_price)) / body
            if body > 0
            else 0.0
        )
        clean_breakout = upper_shadow <= self.config.max_upper_shadow

        rebound = rebound_pct(snap)
        rel = relative_strength(snap)

        factors = [
            FactorContribution(
                key="platform_range",
                label="平台振幅",
                value=round2(platform_range_pct),
                score=round(_score_platform_range(platform_range_pct), 1),
                description="最近 20 日平台的高低差比例，越窄越说明横盘充分",
            ),
            FactorContribution(
                key="breakout_height",
                label="突破幅度",
                value=round2((platform_high - last_price) / platform_high * 100 * -1),
                score=round(_score_breakout(last_price, platform_high), 1),
                description="最新价相对平台高点的偏离，正值表示已突破",
            ),
            FactorContribution(
                key="breakout_hold_minutes",
                label="突破后维持分钟数",
                value=hold_minutes,
                score=round(_score_hold(hold_minutes, self.config), 1),
                description="突破后维持的时间，过短视为假突破",
            ),
            FactorContribution(
                key="volume_multiple",
                label="量比倍数",
                value=round2(volume_ratio) if volume_ratio is not None else 0.0,
                score=round(_score_volume(volume_ratio, self.config), 1),
                description="今日实时量能与近 5 日均量的比值",
            ),
            FactorContribution(
                key="upper_shadow",
                label="上影线/实体",
                value=round2(upper_shadow),
                score=round(_score_shadow(upper_shadow, self.config), 1),
                description="上影线占实体的比例，越小越说明突破扎实",
            ),
            FactorContribution(
                key="rebound",
                label="低点回升",
                value=round2(rebound),
                score=round(clip(rebound / 2.5 * 8, 0, 8), 1),
                description="日内低点回升幅度",
            ),
            FactorContribution(
                key="relative_strength",
                label="相对强度",
                value=round2(rel),
                score=round(clip((rel + 0.5) / 2.5 * 6, 0, 6), 1),
                description="相对上证综指的强弱",
            ),
        ]

        score = sum(item.score for item in factors)
        eligible = (
            breakout_high
            and closed_above_breakout
            and breakout_sustained
            and volume_supported
            and clean_breakout
            and score >= self.config.min_score
        )

        reasons: list[str] = []
        if not breakout_high:
            reasons.append(f"今日最高 {today_high:.2f} 未突破平台高点 {platform_high:.2f}")
        if not closed_above_breakout:
            reasons.append("尾盘价未站上平台高点")
        if not breakout_sustained:
            reasons.append(f"突破后维持仅 {hold_minutes} 分钟，未达到 {self.config.min_breakout_hold_minutes}")
        if not volume_supported:
            reasons.append(f"量能倍数 {volume_ratio} 未达到 {self.config.volume_multiple}")
        if not clean_breakout:
            reasons.append(f"上影线/实体 {upper_shadow:.2f} 过高，疑似冲高回落")
        reason = "；".join(reasons) or (
            f"突破 20 日平台高点 {platform_high:.2f}，"
            f"尾盘价 {last_price:.2f} 维持 {hold_minutes} 分钟，"
            f"量能倍数 {volume_ratio:.2f}"
        )

        risk_level = "high" if snap.pct_change <= -2.0 or upper_shadow > 1.0 else "medium" if upper_shadow > 0.5 else "low"

        return Signal(
            code=snap.code,
            name=snap.name,
            score=round(score, 1),
            eligible=eligible,
            reason=reason,
            risk_level=risk_level,
            snapshot=snap,
            factors=factors,
            priority_tags=self._priority_tags(context, eligible, platform_high, hold_minutes, volume_ratio, upper_shadow),
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
                key="breakout_confirmation",
                label="平台放量突破 + 尾盘确认",
                priority=3,
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
        platform_high: float,
        hold_minutes: int,
        volume_ratio: Optional[float],
        upper_shadow: float,
    ) -> list[PriorityTag]:
        evidence = [
            f"平台高点 {platform_high:.2f}",
            f"突破后维持 {hold_minutes} 分钟",
            f"量能倍数 {volume_ratio:.2f}" if volume_ratio is not None else "量能数据缺失",
            f"上影线/实体 {upper_shadow:.2f}",
        ]
        status = "matched" if eligible else "partial"
        return [PriorityTag(
            key="breakout_confirmation",
            label="平台放量突破 + 尾盘确认",
            priority=3,
            status=status,
            evidence=evidence,
        )]

    def definition(self) -> dict:
        return {
            "id": self.strategy_id,
            "version": self.version,
            "name": self.name,
            "summary": "在最近 20 日平台高点放量突破，且尾盘维持时间够长、上影线不夸张。",
            "execution_window": "14:30–15:00",
            "risk_rule": "仅研究信号；历史或分时数据缺失时直接标记为待验证。",
            "factors": [
                "平台振幅",
                "突破幅度",
                "突破后维持分钟数",
                "量能倍数",
                "上影线比例",
                "低点回升",
                "相对强度",
            ],
        }


def _score_platform_range(value: float) -> float:
    return clip((15.0 - value) / 15.0 * 14, 0, 14)


def _score_breakout(price: float, platform_high: float) -> float:
    if platform_high <= 0:
        return 0.0
    return clip((price / platform_high - 1) * 100 / 3 * 16, 0, 16)


def _score_hold(minutes: int, config: P3Config) -> float:
    return clip(minutes / 30 * 14, 0, 14) if minutes else 0.0


def _score_volume(ratio: Optional[float], config: P3Config) -> float:
    if ratio is None:
        return 0.0
    return clip((ratio - 1.0) / (config.volume_multiple - 1.0) * 14, 0, 14)


def _score_shadow(value: float, config: P3Config) -> float:
    if value <= 0:
        return 14.0
    return clip((config.max_upper_shadow - value) / config.max_upper_shadow * 14, 0, 14)
