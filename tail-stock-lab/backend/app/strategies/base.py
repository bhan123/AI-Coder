from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Mapping

from app.models import MarketContext, MarketSnapshot, PriorityTag, Signal


class Strategy(ABC):
    strategy_id: str
    version: str
    name: str
    requires_history: bool = True
    requires_intraday: bool = True
    requires_sectors: bool = True
    max_enrichment_candidates: int | None = None

    def is_executable_at(self, observed_at: datetime) -> bool:
        """Whether this strategy may publish a live signal at the timestamp."""
        from app.service import StrategyService
        return StrategyService._is_tail_window(observed_at)

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> Signal:
        """Backward-compatible entry point using only the snapshot.

        新策略通常携带 ``evaluate_context``；实现者需要保证 ``evaluate`` 至少能用
        snapshot 给出合理的 ``Signal``，从而旧链路不会因为数据缺失而炸掉。
        """

    @abstractmethod
    def evaluate_context(self, context: MarketContext) -> Signal:
        """Evaluate against the full market context (history + intraday + sector).

        默认实现退化为 ``evaluate``，方便现有 fishing_v1 直接接入而不丢失旧逻辑。
        """

    @abstractmethod
    def definition(self) -> dict:
        """Return the human-readable rule contract shown in the UI."""

    def priority_tags(self, context: MarketContext) -> list[PriorityTag]:
        """每个策略单独声明自己的优先级标签；V1 默认不输出额外的 P1–P4。"""
        return []

    def should_enrich_context(self, context: MarketContext) -> bool:
        """Cheap sector/snapshot prefilter before expensive per-stock data calls."""
        return True

    def enrichment_priority(self, context: MarketContext) -> float:
        """Rank cheap candidates before a capped external-data enrichment pass."""
        return 0.0

    def current_config(self) -> dict:
        """Return the current effective configuration for inspection/UI."""
        return getattr(self, "config", {}).__dict__ if hasattr(self, "config") else {}

    def with_overrides(self, overrides: Mapping[str, Any]) -> "Strategy":
        """Return a new strategy instance with the given config overrides applied."""
        if not hasattr(self, "config"):
            return self
        from dataclasses import replace
        try:
            new_cfg = replace(self.config, **{k: v for k, v in overrides.items() if k in self.config.__dataclass_fields__})
        except (TypeError, ValueError):
            return self
        return type(self)(new_cfg)
