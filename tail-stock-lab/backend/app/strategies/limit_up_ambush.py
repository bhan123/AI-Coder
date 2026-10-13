"""盘中涨停伏击预警。

这不是涨停承诺，也不包含自动交易。它只利用全市场快照和行业成员映射，
寻找板块同步走强、个股放量接近涨停但尚未封板的盘中观察对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.models import FactorContribution, MarketContext, MarketSnapshot, Signal
from app.strategies._factors import apply_overrides, clip, config_to_dict, round2
from app.strategies.base import Strategy


@dataclass(frozen=True)
class LimitUpAmbushConfig:
    min_limit_progress_pct: float = 40.0
    max_limit_progress_pct: float = 94.0
    min_volume_ratio: float = 1.5
    min_turnover_rate: float = 3.0
    min_sector_average_pct: float = 1.0
    min_positive_peers: int = 3
    min_stock_vs_sector_pct: float = 1.5
    min_recent_snapshots: int = 3
    min_momentum_pct: float = 0.3
    min_market_pct: float = -1.0
    min_market_breadth_pct: float = 35.0
    min_sector_momentum_pct: float = 0.0
    min_score: float = 68.0


class LimitUpAmbushAlertStrategy(Strategy):
    strategy_id = "limit-up-ambush"
    version = "0.2.0"
    name = "盘中涨停伏击预警"
    requires_history = False
    requires_intraday = False
    requires_sectors = True

    def __init__(self, config: LimitUpAmbushConfig | None = None) -> None:
        self.config = config or LimitUpAmbushConfig()

    def current_config(self) -> dict:
        return config_to_dict(self.config)

    def with_overrides(self, overrides: dict) -> "LimitUpAmbushAlertStrategy":
        return LimitUpAmbushAlertStrategy(apply_overrides(self.config, overrides))

    @staticmethod
    def board_limit_pct(code: str) -> float:
        if code.startswith(("300", "301", "688", "689")):
            return 20.0
        if code.startswith(("8", "9")):
            return 30.0
        return 10.0

    def limit_progress_pct(self, snap: MarketSnapshot) -> float:
        return snap.pct_change / self.board_limit_pct(snap.code) * 100

    @staticmethod
    def is_executable_at(observed_at: datetime) -> bool:
        local = observed_at.astimezone(ZoneInfo("Asia/Shanghai")) if observed_at.tzinfo else observed_at
        if local.weekday() >= 5:
            return False
        now = local.time()
        return time(9, 35) <= now <= time(10, 30) or time(13, 30) <= now <= time(14, 30)

    def should_enrich_context(self, context: MarketContext) -> bool:
        progress = self.limit_progress_pct(context.snapshot)
        return self.config.min_limit_progress_pct <= progress <= self.config.max_limit_progress_pct

    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        return self.evaluate_context(MarketContext(snapshot=snapshot))

    def evaluate_context(self, context: MarketContext) -> Signal:
        snap = context.snapshot
        if context.sector is None:
            return self._not_ready(snap, "未取得行业归属，无法验证板块联动")

        members = [snap, *context.sector_peers]
        sector_average = sum(member.pct_change for member in members) / len(members)
        positive_peers = sum(1 for member in context.sector_peers if member.pct_change > 0)
        stock_vs_sector = snap.pct_change - sector_average
        recent = context.recent_snapshots[-self.config.min_recent_snapshots:]
        momentum_pct = recent[-1].pct_change - recent[0].pct_change if len(recent) >= self.config.min_recent_snapshots else 0.0
        momentum_ready = (
            len(recent) >= self.config.min_recent_snapshots
            and momentum_pct >= self.config.min_momentum_pct
            and all(current.pct_change > previous.pct_change for previous, current in zip(recent, recent[1:]))
            and all(current.price > previous.price for previous, current in zip(recent, recent[1:]))
        )
        limit_progress = self.limit_progress_pct(snap)
        in_price_band = self.config.min_limit_progress_pct <= limit_progress <= self.config.max_limit_progress_pct
        volume_ready = snap.volume_ratio >= self.config.min_volume_ratio
        turnover_ready = snap.turnover_rate >= self.config.min_turnover_rate
        market_breadth = context.market_breadth_pct or 0.0
        market_ready = (
            snap.market_pct_change >= self.config.min_market_pct
            and context.market_breadth_pct is not None
            and market_breadth >= self.config.min_market_breadth_pct
        )
        sector_ready = sector_average >= self.config.min_sector_average_pct
        sector_history = context.recent_sector_average_pcts[-self.config.min_recent_snapshots:]
        sector_momentum_pct = (
            sector_history[-1] - sector_history[0]
            if len(sector_history) >= self.config.min_recent_snapshots else 0.0
        )
        sector_momentum_ready = (
            len(sector_history) >= self.config.min_recent_snapshots
            and sector_momentum_pct >= self.config.min_sector_momentum_pct
            and sector_history[-1] >= sector_history[-2]
        )
        resonance_ready = positive_peers >= self.config.min_positive_peers
        leader_ready = stock_vs_sector >= self.config.min_stock_vs_sector_pct

        def factor(key: str, label: str, value: float, score: float, description: str) -> FactorContribution:
            return FactorContribution(key=key, label=label, value=value, score=score, description=description)

        factors = [
            factor("stock_strength", "距涨停进度", round2(limit_progress), round(clip((limit_progress - 30) / 64 * 24, 0, 24), 1), "按对应交易板涨停幅度归一化，预警区间为涨停路程的 40%–94%"),
            factor("price_momentum", "连续增强", round2(momentum_pct), round(clip(momentum_pct / self.config.min_momentum_pct * 10, 0, 10), 1), "最近 3 个两分钟快照的价格与涨幅必须逐次抬高"),
            factor("volume_ratio", "量比", round2(snap.volume_ratio), round(clip((snap.volume_ratio - 1) / 2 * 20, 0, 20), 1), "量比至少 1.5，避免无量冲高"),
            factor("turnover", "换手率", round2(snap.turnover_rate), round(clip(snap.turnover_rate / 10 * 10, 0, 10), 1), "要求足够换手，降低一笔拉升的误报"),
            factor("market_regime", "市场上涨家数占比", round2(market_breadth), round(clip((market_breadth - 35) / 35 * 6, 0, 6), 1), "指数跌幅不超过 1%，且全市场至少 35% 股票上涨"),
            factor("sector_average", "行业平均涨幅", round2(sector_average), round(clip(sector_average / 4 * 8, 0, 8), 1), "基于本次全市场快照内同业成员计算"),
            factor("sector_momentum", "板块连续性", round2(sector_momentum_pct), round(clip(sector_momentum_pct / 0.5 * 6, 0, 6), 1), "最近 3 个两分钟快照中板块平均涨幅未退潮"),
            factor("sector_resonance", "同业上涨家数", positive_peers, round(clip(positive_peers / 8 * 10, 0, 10), 1), "除该股外，同一行业中同步上涨的股票数"),
            factor("stock_vs_sector", "强于行业平均", round2(stock_vs_sector), round(clip(stock_vs_sector / 4 * 6, 0, 6), 1), "个股涨幅需显著强于同业平均"),
        ]
        score = round(sum(factor.score for factor in factors), 1)
        eligible = all((in_price_band, momentum_ready, volume_ready, turnover_ready, market_ready, sector_ready, sector_momentum_ready, resonance_ready, leader_ready, score >= self.config.min_score))
        reason = "盘中强势预警：连续增强、板块联动、放量和个股领涨同时满足" if eligible else "未满足盘中涨停伏击预警的全部条件"
        return Signal(
            code=snap.code, name=snap.name, score=score, eligible=eligible, reason=reason,
            risk_level="medium" if eligible else "high", factors=factors, snapshot=snap,
        )

    def _not_ready(self, snap: MarketSnapshot, reason: str) -> Signal:
        return Signal(code=snap.code, name=snap.name, score=0.0, eligible=False, reason=reason,
                      risk_level="high", factors=[], snapshot=snap)

    def definition(self) -> dict:
        return {
            "id": self.strategy_id,
            "version": self.version,
            "name": self.name,
            "summary": "每 2 分钟扫描一次，按交易板归一化涨停进度，并通过连续增强、市场环境和板块共振确认盘中强势股；不自动交易，不承诺涨停。",
            "execution_window": "09:35–10:30、13:30–14:30（每 2 分钟）",
            "risk_rule": "仅作盘中观察预警。公共行情不含逐笔和实时封单，不能据此判断买卖或保证封板。",
            "factors": ["距对应交易板涨停进度 40%–94%", "最近 3 个两分钟快照连续增强", "市场未退潮", "板块最近 3 个快照未退潮", "量比", "换手率", "行业平均涨幅", "行业上涨家数", "个股强于行业平均"],
        }
