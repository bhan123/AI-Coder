from __future__ import annotations

from dataclasses import dataclass

from app.models import BacktestSummary, NextDayPath, PaperTrade, Signal


@dataclass(frozen=True)
class ExecutionPolicy:
    """所有价格均按可成交路径顺序处理，避免最高价事后偏差。"""

    round_trip_cost_rate: float = 0.0015
    stop_loss_rate: float = 0.03
    trailing_retrace: float = 1 / 3


def simulate_t1_exit(signal: Signal, path: NextDayPath, policy: ExecutionPolicy | None = None) -> PaperTrade:
    policy = policy or ExecutionPolicy()
    if path.code != signal.code or not path.prices:
        raise ValueError("回测路径必须与信号匹配且至少包含一个价格")
    entry = path.entry_price
    break_even = entry * (1 + policy.round_trip_cost_rate)
    stop_price = entry * (1 - policy.stop_loss_rate)
    peak = entry
    touched_breakeven = False
    exit_price = path.prices[-1]
    exit_reason = "morning_cutoff"

    for price in path.prices:
        peak = max(peak, price)
        touched_breakeven = touched_breakeven or price >= break_even
        if price <= stop_price:
            exit_price = price
            exit_reason = "stop_loss"
            break
        # 只有峰值已经高于成本线，才允许按“涨幅回撤 1/3”锁定利润。
        gain = peak - entry
        if peak >= break_even and gain > 0 and price <= peak - gain * policy.trailing_retrace:
            exit_price = price
            exit_reason = "trailing_exit"
            break

    net_return = (exit_price / entry - 1 - policy.round_trip_cost_rate) * 100
    return PaperTrade(
        code=signal.code,
        name=signal.name,
        entry_price=round(entry, 3),
        exit_price=round(exit_price, 3),
        net_return_pct=round(net_return, 2),
        touched_breakeven=touched_breakeven,
        profitable_exit=net_return > 0,
        exit_reason=exit_reason,
        session_low_price=round(min(path.prices), 3),
        session_high_price=round(max(path.prices), 3),
    )


def summarize_backtest(signals: list[Signal], paths: list[NextDayPath], *, mode: str) -> BacktestSummary:
    by_code = {path.code: path for path in paths}
    trades = [simulate_t1_exit(signal, by_code[signal.code]) for signal in signals if signal.code in by_code]
    count = len(trades)
    return BacktestSummary(
        strategy_id="fishing-reversal",
        version="1.0.0",
        mode=mode,
        trade_count=count,
        touched_breakeven_rate=round(sum(trade.touched_breakeven for trade in trades) / count * 100, 1) if count else 0,
        profitable_exit_rate=round(sum(trade.profitable_exit for trade in trades) / count * 100, 1) if count else 0,
        average_net_return_pct=round(sum(trade.net_return_pct for trade in trades) / count, 2) if count else 0,
        trades=trades,
    )
