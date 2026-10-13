"""P4：龙头分歧转一致。

判定要点：
  1. 个股是所属板块的涨幅龙头（前 1 名）或与龙头高度联动；
  2. 个股已经触及或封住涨停；
  3. 封单量在尾盘不再衰减（甚至增加），避免"涨停打开"的诱多；
  4. 板块资金承接：板块涨幅明显超过大盘，且板块换手率高于市场中位水平；
  5. 龙头与板块整体方向一致，避免"个股涨停而板块不跟"的孤立信号。
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
    avg_volume,
    clip,
    config_to_dict,
    limit_up_status,
    rebound_pct,
    relative_strength,
    round2,
    seal_order_trend,
)
from app.strategies.base import Strategy


@dataclass(frozen=True)
class P4Config:
    leader_rank_threshold: int = 3
    min_sector_strength_vs_market: float = 1.0
    seal_window_minutes: int = 15
    min_score: float = 60.0


class LeaderReconvergenceStrategy(Strategy):
    strategy_id = "p4-leader-reconvergence"
    version = "1.1.0"
    name = "P4 龙头分歧转一致"
    requires_history = False
    max_enrichment_candidates = 60

    def __init__(self, config: P4Config | None = None) -> None:
        self.config = config or P4Config()

    def current_config(self) -> dict:
        return config_to_dict(self.config)

    def with_overrides(self, overrides: dict) -> "LeaderReconvergenceStrategy":
        return LeaderReconvergenceStrategy(apply_overrides(self.config, overrides))

    def should_enrich_context(self, context: MarketContext) -> bool:
        snap = context.snapshot
        return (
            context.sector is not None
            and snap.pct_change >= 8.0
            and context.sector.pct_change - snap.market_pct_change
            >= self.config.min_sector_strength_vs_market
        )

    def enrichment_priority(self, context: MarketContext) -> float:
        sector_strength = context.sector.pct_change if context.sector else 0.0
        return context.snapshot.pct_change * 2 + sector_strength

    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        return self.evaluate_context(MarketContext(snapshot=snapshot))

    def evaluate_context(self, context: MarketContext) -> Signal:
        snap = context.snapshot
        sector = context.sector
        if sector is None:
            return self._missing_signal(snap, "未找到板块归属，无法识别龙头")
        if not context.intraday_bars:
            return self._missing_signal(snap, "缺少分时数据，无法识别封单变化")

        is_leader = sector.leader_code == snap.code
        stock_rank = 1 + sum(
            1 for peer in context.sector_peers if peer.pct_change > snap.pct_change
        )
        is_top_rank = stock_rank <= self.config.leader_rank_threshold

        limit_up = limit_up_status(snap, context.intraday_bars)
        seal_trend = seal_order_trend(context.intraday_bars)

        sector_vs_market = sector.pct_change - snap.market_pct_change
        sector_capital = self._sector_capital_strength(context)

        rebound = rebound_pct(snap)
        rel = relative_strength(snap)

        factors = [
            FactorContribution(
                key="is_leader",
                label="是否板块龙头",
                value=float(is_leader),
                score=20.0 if is_leader else (10.0 if is_top_rank else 0.0),
                description="数据源明确标识的板块龙头，或按同板块个股涨幅排名进入前列",
            ),
            FactorContribution(
                key="stock_rank",
                label="同板块个股涨幅排名",
                value=float(stock_rank),
                score=0.0,
                description="排名由当前快照中的同板块个股涨幅计算，不使用板块强度排名替代",
            ),
            FactorContribution(
                key="limit_up_status",
                label="涨停状态",
                value=_limit_up_score(limit_up),
                score=_limit_up_score(limit_up),
                description="封板 / 触及涨停 / 未触板",
            ),
            FactorContribution(
                key="seal_trend",
                label="封单变化",
                value=_seal_trend_score(seal_trend, limit_up),
                score=_seal_trend_score(seal_trend, limit_up),
                description="尾盘最后 15 分钟相对前 15 分钟的量能变化",
            ),
            FactorContribution(
                key="sector_vs_market",
                label="板块相对市场",
                value=round2(sector_vs_market),
                score=round(clip((sector_vs_market - self.config.min_sector_strength_vs_market) / 3 * 18, 0, 18), 1),
                description="板块涨跌幅超过大盘的幅度",
            ),
            FactorContribution(
                key="sector_capital_strength",
                label="板块资金承接",
                value=round2(sector_capital),
                score=round(clip(sector_capital / 2 * 12, 0, 12), 1),
                description="板块内整体换手率高于市场中位越多，资金承接越强",
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

        score = sum(item.score if isinstance(item.score, (int, float)) else 0 for item in factors)
        eligible = (
            (is_leader or is_top_rank)
            and limit_up in {"sealed", "touched"}
            and seal_trend in {"rising", "stable"}
            and sector_vs_market >= self.config.min_sector_strength_vs_market
            and sector_capital >= 1.0
            and score >= self.config.min_score
        )

        reasons: list[str] = []
        if not (is_leader or is_top_rank):
            reasons.append("个股在板块内排名未进入前 3")
        if limit_up == "none":
            reasons.append("未触及涨停")
        elif limit_up == "touched" and not eligible:
            reasons.append("仅触及涨停但未封板")
        if seal_trend == "falling":
            reasons.append("尾盘封单衰减，疑似炸板")
        if sector_vs_market < self.config.min_sector_strength_vs_market:
            reasons.append(f"板块仅相对市场 {sector_vs_market:.2f}%，资金承接不足")
        if sector_capital < 1.0:
            reasons.append("板块换手率低于市场中位，缺资金承接")
        reason = "；".join(reasons) or (
            f"{'板块龙头' if is_leader else '板块前 3'} 且"
            f"{'封板' if limit_up == 'sealed' else '触板'}，"
            f"封单{seal_trend or '未知'}，板块相对市场 {sector_vs_market:.2f}%"
        )

        risk_level = "high" if seal_trend == "falling" or limit_up == "touched" else "medium"

        return Signal(
            code=snap.code,
            name=snap.name,
            score=round(score, 1),
            eligible=eligible,
            reason=reason,
            risk_level=risk_level,
            snapshot=snap,
            factors=factors,
            priority_tags=self._priority_tags(context, eligible, limit_up, seal_trend, sector_vs_market),
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
                key="leader_reconvergence",
                label="龙头分歧转一致",
                priority=4,
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
        limit_up: Optional[str],
        seal_trend: Optional[str],
        sector_vs_market: float,
    ) -> list[PriorityTag]:
        sector = context.sector
        evidence = [
            f"板块 {sector.name} 当日 {sector.pct_change:.2f}%" if sector else "未找到板块",
            f"龙头 {sector.leader_name} 涨 {sector.leader_pct_change:.2f}%" if sector and sector.leader_name else "板块龙头未知",
            f"板块涨停家数 {sector.limit_up_count}" if sector else "板块涨停家数未知",
            f"个股涨停状态 {limit_up or 'unknown'}",
            f"封单变化 {seal_trend or 'unknown'}",
            f"板块相对市场 {sector_vs_market:.2f}%",
        ]
        status = "matched" if eligible else "partial"
        return [PriorityTag(
            key="leader_reconvergence",
            label="龙头分歧转一致",
            priority=4,
            status=status,
            evidence=evidence,
        )]

    def _sector_capital_strength(self, context: MarketContext) -> float:
        """板块换手率相对市场的倍数，>1 表示资金正在流入。"""
        peers = context.sector_peers + [context.snapshot]
        if not peers:
            return 0.0
        sector_turnover = sum(p.turnover_rate for p in peers) / len(peers)
        # 缺少直接的市场换手中位数，只能用相对强弱代理；这里用 pct_change 偏离度补充。
        sector_strength = sector_turnover / 5.0
        sector_strength += (context.sector.pct_change - context.snapshot.market_pct_change) / 5.0
        return round(sector_strength, 2)

    def definition(self) -> dict:
        return {
            "id": self.strategy_id,
            "version": self.version,
            "name": self.name,
            "summary": "寻找已封板的板块龙头，且封单稳定、板块资金承接、未出现分歧。",
            "execution_window": "14:30–15:00",
            "risk_rule": "仅研究信号；封板被打开或板块不跟随时直接标记为待验证。",
            "factors": [
                "是否板块龙头",
                "涨停状态",
                "封单变化",
                "板块相对市场",
                "板块资金承接",
                "低点回升",
                "相对强度",
            ],
        }


def _limit_up_label(value: Optional[str]) -> str:
    return {"sealed": "封板", "touched": "触板", "none": "未触板"}.get(value or "none", "未知")


def _limit_up_score(value: Optional[str]) -> float:
    return {"sealed": 20.0, "touched": 10.0}.get(value or "", 0.0)


def _seal_trend_score(value: Optional[str], limit_up: Optional[str]) -> float:
    if limit_up != "sealed":
        return 0.0
    return {"rising": 14.0, "stable": 10.0, "falling": 0.0}.get(value or "", 0.0)
