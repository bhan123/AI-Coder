from __future__ import annotations

from datetime import datetime, time
from typing import Iterable, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.data_provider import (
    ContextAssembler,
    HistoryProvider,
    IntradayProvider,
    MarketDataProvider,
    SampleHistoryProvider,
    SampleIntradayProvider,
    SampleSectorProvider,
    SectorProvider,
)
from app.models import StrategyRun
from app.repository import StrategyRepository
from app.strategies.base import Strategy


class StrategyService:
    def __init__(
        self,
        strategy: Strategy,
        repository: StrategyRepository,
        *,
        history: HistoryProvider | None = None,
        intraday: IntradayProvider | None = None,
        sectors: SectorProvider | None = None,
    ) -> None:
        self.strategy = strategy
        self.repository = repository
        self.assembler = ContextAssembler(
            history or SampleHistoryProvider(),
            intraday or SampleIntradayProvider(),
            sectors or SampleSectorProvider(),
        )

    @staticmethod
    def _is_tail_window(observed_at: datetime) -> bool:
        """A live signal is executable only in the declared Shanghai tail window."""
        local = observed_at.astimezone(ZoneInfo("Asia/Shanghai")) if observed_at.tzinfo else observed_at
        return local.weekday() < 5 and time(14, 30) <= local.time() <= time(15, 0)

    def _data_source_label(self, market_source: str, strategy: Strategy | None = None) -> str:
        """Persist every live dependency that participated in this strategy run."""
        strategy = strategy or self.strategy
        sources = [market_source]
        required_sources = (
            (strategy.requires_history, self.assembler.history.source_name),
            (strategy.requires_intraday, self.assembler.intraday.source_name),
            (strategy.requires_sectors, self.assembler.sectors.source_name),
        )
        for required, source_name in required_sources:
            if required and source_name and source_name not in sources:
                sources.append(source_name)
        return " + ".join(sources)

    def run(
        self,
        provider: MarketDataProvider,
        *,
        mode: str,
        observed_at: datetime | None = None,
        capture_origin: Literal["scheduled", "manual"] = "manual",
        persist_snapshots: bool = True,
        recent_snapshots: dict | None = None,
    ) -> StrategyRun:
        observed_at = observed_at or datetime.now(ZoneInfo("Asia/Shanghai"))
        if mode == "sample":
            observed_at = observed_at.replace(hour=14, minute=50, second=0, microsecond=0)
        snapshots = provider.fetch(observed_at)
        contexts = self.assembler.assemble(
            snapshots,
            observed_at,
            recent_snapshots=recent_snapshots,
            history_required=self.strategy.requires_history,
            intraday_required=self.strategy.requires_intraday,
            sector_required=self.strategy.requires_sectors,
            enrich_predicate=self.strategy.should_enrich_context,
            enrich_limit=self.strategy.max_enrichment_candidates,
            enrich_priority=self.strategy.enrichment_priority,
        )
        signals = [self.strategy.evaluate_context(contexts[snap.code]) for snap in snapshots]
        execution_status = "sample" if mode == "sample" else (
            "tradable" if self.strategy.is_executable_at(observed_at) else "outside_tail_window"
        )
        eligible = [] if execution_status == "outside_tail_window" else sorted(
            (signal for signal in signals if signal.eligible), key=lambda item: item.score, reverse=True
        )[:3]
        run = StrategyRun(
            run_id=str(uuid4()), strategy_id=self.strategy.strategy_id, version=self.strategy.version,
            observed_at=observed_at, mode=mode, capture_origin=capture_origin,
            data_source=self._data_source_label(provider.source_name),
            execution_status=execution_status,
            universe_size=len(snapshots), signals=eligible,
        )
        self.repository.save_run(run, snapshots=snapshots if persist_snapshots else None)
        return run

    def preview(self, provider: MarketDataProvider, *, mode: str = "sample", limit: int = 5) -> dict:
        """不在尾盘窗口也允许跑一次，把所有 eligible + 前 N 个 ineligible 都返回，方便评估调参。"""
        observed_at = datetime.now(ZoneInfo("Asia/Shanghai"))
        if mode == "sample":
            observed_at = observed_at.replace(hour=14, minute=50, second=0, microsecond=0)
        snapshots = provider.fetch(observed_at)
        contexts = self.assembler.assemble(
            snapshots,
            observed_at,
            history_required=self.strategy.requires_history,
            intraday_required=self.strategy.requires_intraday,
            sector_required=self.strategy.requires_sectors,
            enrich_predicate=self.strategy.should_enrich_context,
            enrich_limit=self.strategy.max_enrichment_candidates,
            enrich_priority=self.strategy.enrichment_priority,
        )
        signals = [self.strategy.evaluate_context(contexts[snap.code]) for snap in snapshots]
        eligible = sorted(
            (s for s in signals if s.eligible), key=lambda item: item.score, reverse=True
        )[:limit]
        near_miss = sorted(
            (s for s in signals if not s.eligible), key=lambda item: item.score, reverse=True
        )[:limit]
        return {
            "strategy_id": self.strategy.strategy_id,
            "universe_size": len(snapshots),
            "eligible_count": sum(1 for s in signals if s.eligible),
            "eligible": [s.model_dump(mode="json") for s in eligible],
            "near_miss": [s.model_dump(mode="json") for s in near_miss],
        }

    def run_all_strategies(
        self,
        provider: MarketDataProvider,
        *,
        mode: str,
        observed_at: datetime | None = None,
        strategies: list[Strategy] | None = None,
        capture_origin: Literal["scheduled", "manual"] = "manual",
    ) -> dict[str, StrategyRun]:
        """对一组策略分别跑同一份 context，结果用 strategy_id 做键返回。

        这就是 UI 上"P1 / P2 / P3 / P4 / V1 全部跑一遍"的来源——共用同一份行情快照、
        日线、分时和板块上下文，候选可以横向对比。
        """
        observed_at = observed_at or datetime.now(ZoneInfo("Asia/Shanghai"))
        if mode == "sample":
            observed_at = observed_at.replace(hour=14, minute=50, second=0, microsecond=0)
        snapshots = provider.fetch(observed_at)
        contexts = self.assembler.assemble(snapshots, observed_at)
        runs: dict[str, StrategyRun] = {}
        strategies = strategies or []
        for strategy in strategies:
            signals = [strategy.evaluate_context(contexts[snap.code]) for snap in snapshots]
            execution_status = "sample" if mode == "sample" else (
                "tradable" if self._is_tail_window(observed_at) else "outside_tail_window"
            )
            eligible = [] if execution_status == "outside_tail_window" else sorted(
                (signal for signal in signals if signal.eligible), key=lambda item: item.score, reverse=True
            )[:3]
            run = StrategyRun(
                run_id=str(uuid4()), strategy_id=strategy.strategy_id, version=strategy.version,
                observed_at=observed_at, mode=mode, capture_origin=capture_origin,
                data_source=self._data_source_label(provider.source_name, strategy),
                execution_status=execution_status,
                universe_size=len(snapshots), signals=eligible,
            )
            self.repository.save_run(run, snapshots=snapshots)
            runs[strategy.strategy_id] = run
        return runs
