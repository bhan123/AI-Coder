"""P1：板块共振 + 尾盘回踩企稳。

判定要点：
  1. 个股所在板块当日涨跌幅 > 0，且板块排名靠前；
  2. 同板块至少 N 只个股同步上涨（板块共振）；
  3. 尾盘 14:00–15:00 价格多次站上分时均价线（均价支撑）；
  4. 14:00 之后的 5 分钟均量 < 14:00 之前的 30 分钟均量（缩量回踩）；
  5. 不接受单纯尾盘急拉：要求最后 15 分钟未出现 1% 以上单段跳涨。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models import (
    FactorContribution,
    MarketContext,
    MarketSnapshot,
    PriorityTag,
    Signal,
)
from app.strategies._factors import (
    apply_overrides,
    avg_volume,
    clip,
    close_above_vwap_in_window,
    config_to_dict,
    is_in_tail_window,
    is_shrinking,
    rebound_pct,
    relative_strength,
    round2,
)
from app.strategies.base import Strategy


@dataclass(frozen=True)
class P1Config:
    min_stock_pct: float = 1.0
    max_stock_pct: float = 5.0
    min_stock_vs_sector_avg_pct: float = 0.0
    min_sector_pct: float = 0.5
    min_resonance_count: int = 3
    max_sector_rank_ratio: float = 0.3
    min_day_vwap_hold_ratio: float = 60.0
    min_vwap_hold_ratio: float = 55.0
    min_pullback_vwap_gap_pct: float = -0.2
    min_restrengthening_pct: float = 0.2
    min_range_location_pct: float = 75.0
    shrink_ratio: float = 0.7
    max_jump_pct: float = 1.0
    min_score: float = 55.0


class SectorResonancePullbackStrategy(Strategy):
    strategy_id = "p1-sector-resonance"
    version = "1.1.0"
    name = "P1 板块共振 + 尾盘回踩企稳"
    requires_history = False
    max_enrichment_candidates = 120

    def __init__(self, config: P1Config | None = None) -> None:
        self.config = config or P1Config()

    def current_config(self) -> dict:
        return config_to_dict(self.config)

    def with_overrides(self, overrides: dict) -> "SectorResonancePullbackStrategy":
        return SectorResonancePullbackStrategy(apply_overrides(self.config, overrides))

    def should_enrich_context(self, context: MarketContext) -> bool:
        snap = context.snapshot
        resonance = sum(1 for peer in context.sector_peers if peer.pct_change > 0)
        sector_average = _sector_average_pct(context)
        return (
            self.config.min_stock_pct <= snap.pct_change <= self.config.max_stock_pct
            and context.sector is not None
            and context.sector.pct_change >= self.config.min_sector_pct
            and _sector_is_front(
                context.sector_rank,
                context.sector_total,
                self.config.max_sector_rank_ratio,
            )
            and resonance >= self.config.min_resonance_count
            and snap.pct_change - sector_average >= self.config.min_stock_vs_sector_avg_pct
        )

    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        return self.evaluate_context(MarketContext(snapshot=snapshot))

    def evaluate_context(self, context: MarketContext) -> Signal:
        snap = context.snapshot
        sector = context.sector
        sector_pct = sector.pct_change if sector else None
        resonance = sum(1 for peer in context.sector_peers if peer.pct_change > 0)
        sector_average = _sector_average_pct(context)
        stock_vs_sector_average = snap.pct_change - sector_average
        sector_is_front = _sector_is_front(
            context.sector_rank,
            context.sector_total,
            self.config.max_sector_rank_ratio,
        )
        rebound = rebound_pct(snap)
        rel = relative_strength(snap)

        if not context.intraday_bars:
            return self._missing_signal(snap, "分时数据缺失，无法验证均价线与缩量回踩")

        day_vwap_hold = close_above_vwap_in_window(
            context.intraday_bars, start_minute=0, end_minute=240
        )
        vwap_hold = close_above_vwap_in_window(
            context.intraday_bars, start_minute=180, end_minute=240
        )
        if day_vwap_hold is None or vwap_hold is None:
            return self._missing_signal(snap, "尾盘 14:00–15:00 没有分时切片")

        pullback_vwap_gaps = [
            (bar.price / bar.avg_price - 1) * 100
            for bar in context.intraday_bars
            if 180 <= bar.minutes_after_open <= 215 and bar.avg_price > 0
        ]
        if not pullback_vwap_gaps:
            return self._missing_signal(snap, "14:00–14:35 缺少可计算均价线的分时切片")
        pullback_vwap_gap = min(pullback_vwap_gaps)
        pullback_prices = [
            bar.price for bar in context.intraday_bars
            if 180 <= bar.minutes_after_open <= 215
        ]
        restrengthening_prices = [
            bar.price for bar in context.intraday_bars
            if 215 <= bar.minutes_after_open <= 235
        ]
        if not pullback_prices or not restrengthening_prices:
            return self._missing_signal(snap, "14:35–14:55 缺少重新转强所需分时切片")
        pullback_low = min(pullback_prices)
        restrengthening = (
            (max(restrengthening_prices) / pullback_low - 1) * 100
            if pullback_low > 0 else 0.0
        )
        intraday_prices = [bar.price for bar in context.intraday_bars if bar.price > 0]
        intraday_low = min(intraday_prices)
        intraday_high = max(intraday_prices)
        range_location = (
            (intraday_prices[-1] - intraday_low) / (intraday_high - intraday_low) * 100
            if intraday_high > intraday_low else 100.0
        )

        before_avg = avg_volume(context.intraday_bars, start_minute=150, end_minute=179)
        after_avg = avg_volume(context.intraday_bars, start_minute=180, end_minute=215)
        shrinking = (
            is_shrinking(before_avg, after_avg, shrink_pct=self.config.shrink_ratio)
            if before_avg and after_avg
            else None
        )

        last_window = [bar.price for bar in context.intraday_bars if bar.minutes_after_open >= 225]
        jumps: list[float] = []
        for prev, curr in zip(last_window, last_window[1:]):
            if prev > 0:
                jumps.append((curr - prev) / prev * 100)
        max_jump = max(jumps) if jumps else 0.0

        factors = [
            FactorContribution(
                key="stock_strength",
                label="个股当日涨幅",
                value=round2(snap.pct_change),
                score=0.0,
                description="P1 只接受当日已走强但尚未过度加速的 1%–5% 个股",
            ),
            FactorContribution(
                key="stock_vs_sector_average",
                label="个股相对板块平均",
                value=round2(stock_vs_sector_average),
                score=0.0,
                description="个股涨幅减去同板块样本的平均涨幅，避免选择板块内弱跟涨",
            ),
            FactorContribution(
                key="sector_strength",
                label="板块涨跌幅",
                value=round2(sector_pct if sector_pct is not None else 0.0),
                score=round(_score_sector(sector_pct, self.config), 1),
                description="P1 要求板块当日明显上涨，作为板块共振的前提",
            ),
            FactorContribution(
                key="sector_resonance",
                label="同板块同步上涨数",
                value=resonance,
                score=round(_score_resonance(resonance, self.config), 1),
                description="同板块内同步上涨的家数越多，共振越强",
            ),
            FactorContribution(
                key="sector_rank",
                label="板块强度排名",
                value=float(context.sector_rank or 0),
                score=0.0,
                description="按板块当日涨跌幅排序，P1 只接受前 30% 板块",
            ),
            FactorContribution(
                key="day_vwap_hold_ratio",
                label="全天站上均价线占比",
                value=round2(day_vwap_hold),
                score=0.0,
                description="从开盘到信号时刻，价格位于累计均价线上方的切片占比",
            ),
            FactorContribution(
                key="vwap_hold_ratio",
                label="尾盘站上均价线占比",
                value=round2(vwap_hold),
                score=round(_score_vwap(vwap_hold, self.config), 1),
                description="尾盘 30 分钟价格站上分时均价的切片占比",
            ),
            FactorContribution(
                key="pullback_vwap_gap",
                label="回踩相对均价线",
                value=round2(pullback_vwap_gap),
                score=0.0,
                description="14:00–14:35 回踩最低价相对分时均价线的偏离",
            ),
            FactorContribution(
                key="restrengthening",
                label="尾盘重新转强",
                value=round2(restrengthening),
                score=0.0,
                description="14:35–14:55 相对 14:00 后回踩低点的最大回升",
            ),
            FactorContribution(
                key="range_location",
                label="信号时刻日内位置",
                value=round2(range_location),
                score=0.0,
                description="最新价位于当日分时振幅的百分位，P1 要求处于上方四分之一",
            ),
            FactorContribution(
                key="volume_shrink",
                label="尾盘量能衰减",
                value=round((1 - after_avg / before_avg) * 100, 2) if before_avg else 0.0,
                score=round(_score_shrink(shrinking), 1),
                description="14:00–14:35 回踩均量相对 13:30–14:00 均量的衰减",
            ),
            FactorContribution(
                key="rebound",
                label="低点回升",
                value=round2(rebound),
                score=round(clip(rebound / 2.5 * 18, 0, 18), 1),
                description="从日内低点回升的幅度",
            ),
            FactorContribution(
                key="relative_strength",
                label="相对强度",
                value=round2(rel),
                score=round(clip((rel + 0.5) / 2.5 * 12, 0, 12), 1),
                description="相对上证综指的强弱",
            ),
            FactorContribution(
                key="max_jump",
                label="尾盘单段最大涨幅",
                value=round2(max_jump),
                score=round(clip((self.config.max_jump_pct - max_jump) / self.config.max_jump_pct * 8, 0, 8), 1),
                description="剔除尾盘急拉，避免抢筹陷阱",
            ),
        ]

        score = min(100.0, sum(item.score for item in factors))
        eligible = (
            self.config.min_stock_pct <= snap.pct_change <= self.config.max_stock_pct
            and stock_vs_sector_average >= self.config.min_stock_vs_sector_avg_pct
            and sector is not None
            and sector_pct is not None
            and sector_pct >= self.config.min_sector_pct
            and sector_is_front
            and resonance >= self.config.min_resonance_count
            and day_vwap_hold >= self.config.min_day_vwap_hold_ratio
            and vwap_hold >= self.config.min_vwap_hold_ratio
            and pullback_vwap_gap >= self.config.min_pullback_vwap_gap_pct
            and restrengthening >= self.config.min_restrengthening_pct
            and range_location >= self.config.min_range_location_pct
            and shrinking is True
            and max_jump <= self.config.max_jump_pct
            and score >= self.config.min_score
        )

        if eligible:
            reason = (
                f"板块 {sector.name} 涨 {sector_pct:.2f}%，"
                f"同板块 {resonance} 只同步上涨，"
                f"尾盘站上均价线占比 {vwap_hold:.1f}%，14:00 后量能明显萎缩"
            )
        else:
            reasons: list[str] = []
            if not self.config.min_stock_pct <= snap.pct_change <= self.config.max_stock_pct:
                reasons.append(
                    f"个股涨幅 {snap.pct_change:.2f}% 不在 "
                    f"{self.config.min_stock_pct:.1f}%–{self.config.max_stock_pct:.1f}%"
                )
            if stock_vs_sector_average < self.config.min_stock_vs_sector_avg_pct:
                reasons.append(
                    f"个股弱于板块平均 {abs(stock_vs_sector_average):.2f}%"
                )
            if sector is None or sector_pct is None:
                reasons.append("未找到板块归属或板块涨跌幅")
            elif sector_pct < self.config.min_sector_pct:
                reasons.append(f"板块仅 {sector_pct:.2f}%，未达到共振阈值")
            if not sector_is_front:
                if context.sector_rank is None or context.sector_total is None:
                    reasons.append("板块强度排名缺失")
                else:
                    reasons.append(f"板块排名 {context.sector_rank}/{context.sector_total}，未进入前 30%")
            if resonance < self.config.min_resonance_count:
                reasons.append(f"同板块同步上涨仅 {resonance} 只")
            if day_vwap_hold < self.config.min_day_vwap_hold_ratio:
                reasons.append(
                    f"全天站上均价线占比 {day_vwap_hold:.1f}% < "
                    f"{self.config.min_day_vwap_hold_ratio}%"
                )
            if vwap_hold < self.config.min_vwap_hold_ratio:
                reasons.append(f"尾盘站上均价线占比 {vwap_hold:.1f}% < {self.config.min_vwap_hold_ratio}%")
            if pullback_vwap_gap < self.config.min_pullback_vwap_gap_pct:
                reasons.append(
                    f"14:00 后回踩跌破均价线 {abs(pullback_vwap_gap):.2f}%"
                )
            if restrengthening < self.config.min_restrengthening_pct:
                reasons.append(
                    f"14:35–14:55 未重新转强（仅回升 {restrengthening:.2f}%）"
                )
            if range_location < self.config.min_range_location_pct:
                reasons.append(
                    f"最新价未处于日内振幅上方四分之一（{range_location:.1f}%）"
                )
            if shrinking is False:
                reasons.append("14:00 后未出现明显缩量回踩")
            if max_jump > self.config.max_jump_pct:
                reasons.append(f"尾盘出现 {max_jump:.2f}% 跳涨，疑似急拉")
            reason = "；".join(reasons) or "评分不足"

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
            priority_tags=self._priority_tags(context, eligible, sector_pct, resonance, vwap_hold, shrinking),
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
                key="sector_resonance_pullback",
                label="板块共振 + 尾盘回踩企稳",
                priority=1,
                status="missing_data",
                evidence=[reason],
            )],
        )

    def priority_tags(self, context: MarketContext) -> list[PriorityTag]:
        return []  # 在 evaluate_context 中已构造并附带

    def _priority_tags(
        self,
        context: MarketContext,
        eligible: bool,
        sector_pct: Optional[float],
        resonance: int,
        vwap_hold: float,
        shrinking: Optional[bool],
    ) -> list[PriorityTag]:
        sector = context.sector
        if sector is None:
            return [PriorityTag(
                key="sector_resonance_pullback",
                label="板块共振 + 尾盘回踩企稳",
                priority=1,
                status="missing_data",
                evidence=["未找到个股所属板块，无法判定板块共振"],
            )]
        evidence = [
            f"板块 {sector.name} 当日 {sector_pct:.2f}%",
            f"板块排名 {context.sector_rank}/{context.sector_total}" if context.sector_rank else "板块排名未计算",
            f"同板块同步上涨 {resonance} 只",
            f"尾盘站上均价线占比 {vwap_hold:.1f}%",
            "14:00 后缩量回踩" if shrinking else "未观察到 14:00 后缩量回踩",
        ]
        if eligible:
            status: str = "matched"
        elif sector_pct is None or sector_pct < self.config.min_sector_pct or resonance < self.config.min_resonance_count:
            status = "partial"
        elif vwap_hold < self.config.min_vwap_hold_ratio or shrinking is False:
            status = "partial"
        else:
            status = "partial"
        return [PriorityTag(
            key="sector_resonance_pullback",
            label="板块共振 + 尾盘回踩企稳",
            priority=1,
            status=status,
            evidence=evidence,
        )]

    def definition(self) -> dict:
        return {
            "id": self.strategy_id,
            "version": self.version,
            "name": self.name,
            "summary": "寻找板块强势 + 同板块多股共振 + 尾盘均价支撑且 14:00 后缩量回踩的个股。",
            "execution_window": "14:30–15:00",
            "risk_rule": "仅研究信号；分时缺失时直接标记为待验证，不估算分数。",
            "factors": [
                "板块涨跌幅",
                "个股当日涨幅 1%–5%",
                "个股强于板块平均",
                "板块强度排名",
                "板块内共振家数",
                "全天站上均价线占比",
                "尾盘站上均价线占比",
                "14:00 后回踩不有效跌破均价线",
                "14:35–14:55 重新转强",
                "信号时刻位于日内振幅上方四分之一",
                "14:00 后缩量回踩",
                "低点回升",
                "相对强度",
                "尾盘跳涨幅度",
            ],
        }


def _score_sector(value: Optional[float], config: P1Config) -> float:
    if value is None:
        return 0.0
    return clip((value - 0.0) / 3.0 * 22, 0, 22)


def _sector_average_pct(context: MarketContext) -> float:
    members = [context.snapshot, *context.sector_peers]
    return sum(member.pct_change for member in members) / len(members)


def _sector_is_front(rank: Optional[int], total: Optional[int], ratio: float) -> bool:
    if rank is None or total is None or total <= 0:
        return False
    return rank <= max(1, int(total * ratio))


def _score_resonance(resonance: int, config: P1Config) -> float:
    return clip((resonance - config.min_resonance_count + 1) / 3 * 18, 0, 18)


def _score_vwap(value: float, config: P1Config) -> float:
    return clip((value - config.min_vwap_hold_ratio) / (100 - config.min_vwap_hold_ratio) * 20, 0, 20)


def _score_shrink(value: Optional[bool]) -> float:
    return 16.0 if value else 0.0
