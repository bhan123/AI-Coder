from __future__ import annotations

from datetime import date, datetime
from math import isfinite
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class MarketSnapshot(BaseModel):
    code: str
    name: str
    price: float
    pct_change: float
    day_low: float
    turnover_rate: float = 0.0
    volume_ratio: float = 0.0
    market_pct_change: float = 0.0
    captured_at: datetime

    @field_validator("volume_ratio", mode="before")
    @classmethod
    def normalize_missing_volume_ratio(cls, value: object) -> float:
        """行情源的 NaN/空量比视为缺失，避免写入 SQLite 时变成 NULL。"""
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return 0.0
        return normalized if isfinite(normalized) else 0.0


class FactorContribution(BaseModel):
    key: str
    label: str
    value: float
    score: float
    description: str


class PriorityTag(BaseModel):
    key: str
    label: str
    priority: int
    status: Literal["partial", "missing_data", "excluded", "matched"]
    evidence: list[str]


class Signal(BaseModel):
    code: str
    name: str
    score: float = Field(ge=0, le=100)
    eligible: bool
    reason: str
    risk_level: Literal["low", "medium", "high"]
    factors: list[FactorContribution]
    snapshot: MarketSnapshot
    priority_tags: list[PriorityTag] = Field(default_factory=list)


class StrategyRun(BaseModel):
    run_id: str
    strategy_id: str
    version: str
    observed_at: datetime
    mode: Literal["live", "sample"]
    capture_origin: Literal["scheduled", "manual"] = "manual"
    data_source: str = "unknown"
    execution_status: Literal["sample", "tradable", "outside_tail_window"] = "sample"
    universe_size: int
    signals: list[Signal]


class NextDayPath(BaseModel):
    """T+1 可交易时段的顺序价格路径；不能用当日最高价倒推成交。"""
    code: str
    entry_price: float
    prices: list[float]
    observed_at: datetime


class T1PricePoint(BaseModel):
    """A real next-day minute quote retained for the review chart."""
    time: str
    price: float


class T1MarketReview(BaseModel):
    """Observed next-day movement, separate from the simulated exit decision."""
    observed_at: datetime
    open_price: float
    high_price: float
    low_price: float
    last_price: float
    points: list[T1PricePoint]


class PaperTrade(BaseModel):
    code: str
    name: str
    entry_price: float
    exit_price: float
    net_return_pct: float
    touched_breakeven: bool
    profitable_exit: bool
    exit_reason: Literal["stop_loss", "trailing_exit", "morning_cutoff"]
    session_low_price: float | None = None
    session_high_price: float | None = None
    market_review: T1MarketReview | None = None


class BacktestSummary(BaseModel):
    strategy_id: str
    version: str
    mode: Literal["sample", "historical"]
    trade_count: int
    touched_breakeven_rate: float
    profitable_exit_rate: float
    average_net_return_pct: float
    trades: list[PaperTrade]


class DailyBar(BaseModel):
    """单日 K 线，是 P2/P3 计算均线、平台和突破的依据。"""

    code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    turnover_rate: float = 0.0


class IntradayBar(BaseModel):
    """当日分时切片，是 P1 均价线和缩量回踩、P3 突破后维持、P4 封单变化的依据。"""

    code: str
    minutes_after_open: int = Field(ge=0, le=240)
    price: float
    avg_price: float = 0.0
    volume: float = 0.0


class SectorQuote(BaseModel):
    """板块行情，pct_change 由板块内全部 A 股加权计算得到。"""

    code: str
    name: str
    pct_change: float
    leader_code: Optional[str] = None
    leader_name: Optional[str] = None
    leader_pct_change: float = 0.0
    limit_up_count: int = 0


class MarketContext(BaseModel):
    """策略评估上下文：将个股截面、日线、分时和板块四类数据并入一个不可变视图。

    新策略以 MarketContext 为入参；旧 V1 仍可只消费 snapshot，但同时可通过 context
    拉取额外数据来校准 priority_tags 的"待验证"标签，避免再被指责为虚假标注。
    """

    snapshot: MarketSnapshot
    recent_snapshots: list[MarketSnapshot] = Field(default_factory=list)
    market_breadth_pct: Optional[float] = None
    recent_sector_average_pcts: list[float] = Field(default_factory=list)
    daily_history: list[DailyBar] = Field(default_factory=list)
    intraday_bars: list[IntradayBar] = Field(default_factory=list)
    sector: Optional[SectorQuote] = None
    sector_peers: list[MarketSnapshot] = Field(default_factory=list)
    sector_rank: Optional[int] = None
    sector_total: Optional[int] = None
