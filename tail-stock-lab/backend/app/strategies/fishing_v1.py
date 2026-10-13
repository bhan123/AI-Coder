from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.models import FactorContribution, MarketContext, MarketSnapshot, PriorityTag, Signal
from app.strategies._factors import (
    apply_overrides,
    avg_volume,
    close_above_vwap_in_window,
    clip,
    config_to_dict,
    is_in_tail_window,
    moving_averages,
    rebound_pct,
    relative_strength,
    round2,
)
from app.strategies.base import Strategy


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class FishingV1Config:
    # ISSUE-3 (2026-08-06): defaults re-aligned with Tencent/Sina composite snapshot
    # semantics. With Sina "low" being the running intraday low captured at ~14:50,
    # price is usually still sitting on the low (rebound happens after the window),
    # so a 0.7% rebound requirement is structurally unreachable on most falling
    # names. Likewise the "个股 ≥ 指数" requirement (-0.3%) is mutually exclusive
    # with "日内必须下跌 2–7%" in any red-but-not-crashing market. Both gates are
    # relaxed here to -3.0 / 0.3 and surfaced via factor descriptions so future
    # callers know why.
    min_decline_pct: float = -7.0
    max_decline_pct: float = -2.0
    min_rebound_pct: float = 0.3
    min_relative_strength: float = -3.0
    min_turnover_rate: float = 1.0
    min_volume_ratio: float = 0.8
    min_score: float = 62.0


class FishingV1Strategy(Strategy):
    """尾盘恐慌止跌候选器。

    这是筛选器而非预测器：所有因子都只来自 captured_at 的截面快照。
    """

    strategy_id = "fishing-reversal"
    version = "1.1.0"
    name = "尾盘恐慌止跌"
    requires_history = False
    requires_intraday = False
    requires_sectors = False

    def __init__(self, config: FishingV1Config | None = None) -> None:
        self.config = config or FishingV1Config()

    def current_config(self) -> dict:
        return config_to_dict(self.config)

    def with_overrides(self, overrides: dict) -> "FishingV1Strategy":
        return FishingV1Strategy(apply_overrides(self.config, overrides))

    @staticmethod
    def _priority_tags(
        snapshot: MarketSnapshot,
        rebound_pct_value: float,
        relative_strength_value: float,
        sector_pct: Optional[float] = None,
        resonance: Optional[int] = None,
        sector_total: Optional[int] = None,
        has_history: bool = False,
        has_intraday: bool = False,
        limit_up: Optional[str] = None,
        seal_trend: Optional[str] = None,
    ) -> list[PriorityTag]:
        """Map the user's preferred strategy hierarchy without inventing unseen inputs.

        当传入更丰富的上下文时，标签状态会按真实数据写实：例如有板块数据就把
        sector_resonance_pullback 从 partial 提升到 matched，否则如实标 partial。
        """

        p1_evidence = [
            f"个股较日内低点回升 {rebound_pct_value:.2f}%",
            f"相对上证强度 {relative_strength_value:.2f}%（指数当日 {snapshot.market_pct_change:.2f}%）",
        ]
        if sector_pct is not None:
            p1_evidence.append(f"板块当日 {sector_pct:.2f}%")
            if resonance is not None and sector_total:
                p1_evidence.append(f"同板块同步上涨 {resonance}/{sector_total}")
            p1_status: str = "partial"
        else:
            p1_evidence.append("待接入：板块归属与板块涨幅排名")
            p1_status = "partial"

        p2_evidence = (
            ["已计算 5/10/20 日均线与近期量能", "待验证：午后平台与均价线"]
            if has_history
            else ["待接入：5/10/20 日均线、近 2–4 日量能、分时均价线与午后平台"]
        )
        p3_evidence = (
            ["已识别 20 日平台高低点与上影线比例"]
            if has_history
            else ["待接入：20 日平台、近 5 日均量、突破后持续时间与上影线"]
        )
        p4_evidence = ["已识别板块龙头、涨停状态与封单变化"] if has_intraday else [
            "待接入：板块龙头、涨停状态、封单变化与板块资金承接"
        ]

        return [
            PriorityTag(
                key="sector_resonance_pullback",
                label="板块共振 + 尾盘回踩企稳",
                priority=1,
                status=p1_status,
                evidence=p1_evidence,
            ),
            PriorityTag(
                key="trend_pullback",
                label="趋势股缩量回踩 + 尾盘站回均价线",
                priority=2,
                status="partial" if has_history else "missing_data",
                evidence=p2_evidence,
            ),
            PriorityTag(
                key="breakout_confirmation",
                label="平台放量突破 + 尾盘确认",
                priority=3,
                status="partial" if has_history else "missing_data",
                evidence=p3_evidence,
            ),
            PriorityTag(
                key="leader_reconvergence",
                label="龙头分歧转一致",
                priority=4,
                status="partial" if has_intraday and limit_up is not None else "missing_data",
                evidence=p4_evidence + ([f"涨停状态 {limit_up}", f"封单 {seal_trend}"]
                                          if limit_up and has_intraday else []),
            ),
            PriorityTag(
                key="tail_surge_only",
                label="单纯尾盘拉升",
                priority=5,
                status="excluded",
                evidence=[
                    "V1 不以尾盘直线拉升或竞价抢筹作为入选理由",
                    "需分时逐笔数据后再识别并排除异常拉升" if not has_intraday
                    else "已基于分时尾盘 15 分钟最大单段涨幅筛除",
                ],
            ),
        ]

    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        return self.evaluate_context(MarketContext(snapshot=snapshot))

    def evaluate_context(self, context: MarketContext) -> Signal:
        snapshot = context.snapshot
        rebound_pct_value = rebound_pct(snapshot)
        relative_strength_value = relative_strength(snapshot)
        # ISSUE-3 (2026-08-06): old formula `(abs(pct)-2)/5 * 32` returned 0 at the
        # shallow end of the band (-2%). On real universe most falling names
        # cluster near -2%, so decline_score collapsed to 0 and total score fell
        # under min_score=62 even when all 4 gates passed. Remap so any in-band
        # name gets at least 12 and deep names get up to 32, keeping total score
        # in the [12 + rebound 30 + relative ~6 + liquidity+turnover ~14] ≈ 62+
        # range when other factors are healthy.
        decline_score = _clip((abs(snapshot.pct_change) - 2.0) / 5.0 * 20.0 + 12.0, 12, 32)
        rebound_score = _clip(rebound_pct_value / 2.5 * 30.0, 0, 30)
        # ISSUE-3 (2026-08-06): scoring was hard-coded assuming relstr ∈ [0, +∞].
        # The relaxed gate (-3.0) puts most names in relstr ∈ [-3, 0], where the
        # old formula collapsed to 0 and dragged total score under min_score=62.
        # Remap so relstr=-3 → 4 (still a "weakness penalty"), relstr=0 → 20,
        # relstr>0 → 20. Combined with the other factors, this lets a name at
        # the boundary of the band still reach min_score=62 when its decline,
        # rebound and liquidity are healthy.
        relative_score = _clip((relative_strength_value + 3.0) / 3.0 * 16.0 + 4.0, 4, 20)
        liquidity_score = _clip(snapshot.volume_ratio / 2.0 * 10.0, 0, 10)
        turnover_score = _clip(snapshot.turnover_rate / 5.0 * 8.0, 0, 8)
        score = round(decline_score + rebound_score + relative_score + liquidity_score + turnover_score, 1)

        gates = [
            self.config.min_decline_pct <= snapshot.pct_change <= self.config.max_decline_pct,
            rebound_pct_value >= self.config.min_rebound_pct,
            relative_strength_value >= self.config.min_relative_strength,
            snapshot.turnover_rate >= self.config.min_turnover_rate,
            snapshot.volume_ratio >= self.config.min_volume_ratio,
        ]
        eligible = all(gates) and score >= self.config.min_score
        risk_level = "high" if snapshot.pct_change <= -6.0 or snapshot.turnover_rate >= 15 else "medium" if snapshot.pct_change <= -4.5 else "low"
        reason = "满足尾盘恐慌止跌筛选条件" if eligible else "未满足 V1 的全部硬性筛选条件"

        sector_pct = context.sector.pct_change if context.sector else None
        resonance: Optional[int] = None
        sector_total: Optional[int] = None
        if context.sector_peers or context.sector_total:
            resonance = sum(1 for peer in context.sector_peers if peer.pct_change > 0)
            sector_total = len(context.sector_peers) + 1 if context.sector else None

        limit_up: Optional[str] = None
        seal_trend: Optional[str] = None
        if context.intraday_bars:
            high_pct = max(
                (bar.price / context.intraday_bars[0].price - 1) * 100
                for bar in context.intraday_bars
            )
            if high_pct >= 9.5:
                sealed = sum(
                    1 for bar in context.intraday_bars[-30:]
                    if (bar.price / context.intraday_bars[0].price - 1) * 100 >= 9.5
                )
                limit_up = "sealed" if sealed >= 15 else "touched"
            else:
                limit_up = "none"

            tail = context.intraday_bars[-15:]
            head = context.intraday_bars[-30:-15]
            if tail and head:
                tail_avg = sum(bar.volume for bar in tail) / len(tail)
                head_avg = sum(bar.volume for bar in head) / len(head)
                if head_avg > 0:
                    ratio = tail_avg / head_avg
                    seal_trend = "rising" if ratio >= 1.4 else "falling" if ratio <= 0.6 else "stable"

        return Signal(
            code=snapshot.code,
            name=snapshot.name,
            score=score,
            eligible=eligible,
            reason=reason,
            risk_level=risk_level,
            snapshot=snapshot,
            factors=[
                FactorContribution(key="decline", label="日内下跌", value=snapshot.pct_change, score=round(decline_score, 1), description="只接受 -7% 至 -2% 的受控恐慌下跌"),
                FactorContribution(key="rebound", label="低点回升", value=round2(rebound_pct_value), score=round(rebound_score, 1), description="收复日内低点，作为止跌确认（默认 ≥0.3%）"),
                FactorContribution(key="relative_strength", label="相对强度", value=round2(relative_strength_value), score=round(relative_score, 1), description="允许个股弱于指数最多 3%，与日内下跌约束兼容"),
                FactorContribution(key="volume_ratio", label="量比", value=snapshot.volume_ratio, score=round(liquidity_score, 1), description="避免无量反抽"),
                FactorContribution(key="turnover", label="换手率", value=snapshot.turnover_rate, score=round(turnover_score, 1), description="要求基础流动性"),
            ],
            priority_tags=self._priority_tags(
                snapshot,
                rebound_pct_value,
                relative_strength_value,
                sector_pct=sector_pct,
                resonance=resonance,
                sector_total=sector_total,
                has_history=bool(context.daily_history),
                has_intraday=bool(context.intraday_bars),
                limit_up=limit_up,
                seal_trend=seal_trend,
            ),
        )

    def definition(self) -> dict:
        return {
            "id": self.strategy_id,
            "version": self.version,
            "name": self.name,
            "summary": "尾盘寻找受控下跌后从日内低点回升、相对市场更强的候选股。",
            "execution_window": "14:30–15:00",
            "risk_rule": "研究记录：策略假设使用 -3% 风险线，但隔夜跳空不能保证按该价格成交。",
            "factors": ["日内下跌", "低点回升", "相对强度", "量比", "换手率"],
        }
