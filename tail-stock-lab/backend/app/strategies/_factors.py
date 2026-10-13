"""所有策略共用的数学与判定工具。

不依赖任何 IO，只接受已经落库的截面、日线或分时序列；返回结构化的判定结果，
以便策略主函数把"已核验 / 待验证 / 非主策略"的标签写得更诚实。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace
from datetime import time
from typing import Any, Iterable, Optional

from app.models import DailyBar, IntradayBar, MarketSnapshot


def clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sma(values: Iterable[float], window: int) -> Optional[float]:
    seq = list(values)[-window:]
    if len(seq) < window:
        return None
    return sum(seq) / window


def rebound_pct(snapshot: MarketSnapshot) -> float:
    if snapshot.day_low <= 0:
        return 0.0
    return (snapshot.price - snapshot.day_low) / snapshot.day_low * 100


def relative_strength(snapshot: MarketSnapshot) -> float:
    return snapshot.pct_change - snapshot.market_pct_change


def is_in_tail_window(captured_at_time: time) -> bool:
    return time(14, 30) <= captured_at_time <= time(15, 0)


def avg_volume(bars: list[IntradayBar], *, start_minute: int, end_minute: int) -> float:
    relevant = [bar.volume for bar in bars if start_minute <= bar.minutes_after_open <= end_minute]
    if not relevant:
        return 0.0
    return sum(relevant) / len(relevant)


def last_price(bars: list[IntradayBar], *, at_minute: int) -> Optional[float]:
    candidates = [bar.price for bar in bars if bar.minutes_after_open <= at_minute]
    return candidates[-1] if candidates else None


def close_above_vwap_in_window(bars: list[IntradayBar], *, start_minute: int, end_minute: int) -> Optional[float]:
    """尾盘窗口内，价格站上分时均价的次数占比。返回 None 表示窗口没有数据。"""
    relevant = [bar for bar in bars if start_minute <= bar.minutes_after_open <= end_minute]
    if not relevant:
        return None
    above = sum(1 for bar in relevant if bar.price >= bar.avg_price)
    return above / len(relevant) * 100


def is_shrinking(before: float, after: float, *, shrink_pct: float = 0.7) -> bool:
    """缩量判定：after < before * shrink_pct。"""
    return before > 0 and after > 0 and after < before * shrink_pct


def upper_shadow_ratio(bar: DailyBar) -> float:
    """上影线长度占实体长度的比例，用于识别假突破。"""
    body = abs(bar.close - bar.open)
    if body <= 0:
        return 0.0
    upper = bar.high - max(bar.open, bar.close)
    return upper / body


@dataclass(frozen=True)
class MovingAverageSet:
    ma5: Optional[float]
    ma10: Optional[float]
    ma20: Optional[float]

    @property
    def is_valid(self) -> bool:
        return self.ma5 is not None and self.ma10 is not None and self.ma20 is not None


def moving_averages(history: list[DailyBar]) -> MovingAverageSet:
    closes = [bar.close for bar in history]
    return MovingAverageSet(
        ma5=sma(closes, 5),
        ma10=sma(closes, 10),
        ma20=sma(closes, 20),
    )


def highest_in(history: list[DailyBar], *, window: int, exclude_last: bool = True) -> Optional[float]:
    relevant = history[:-1] if exclude_last else history
    relevant = relevant[-window:] if window else relevant
    if not relevant:
        return None
    return max(bar.high for bar in relevant)


def platform_range(history: list[DailyBar], *, window: int, exclude_last: bool = True) -> Optional[tuple[float, float]]:
    """最近 N 日平台的高低区间（不含最新一根）。返回 None 表示数据不足。"""
    relevant = history[:-1] if exclude_last else history
    relevant = relevant[-window:] if window else relevant
    if len(relevant) < max(5, window // 2):
        return None
    highs = max(bar.high for bar in relevant)
    lows = min(bar.low for bar in relevant)
    return highs, lows


def breakout_confirmed(history: list[DailyBar], intraday: list[IntradayBar], *, platform_high: float, today_open: float) -> bool:
    """平台突破后维持：今日最高>平台最高，且收盘/最新价仍站在开盘之上一定幅度。"""
    if not history:
        return False
    last = history[-1]
    if last.high <= platform_high:
        return False
    if last.close <= today_open:
        return False
    last_price_now = intraday[-1].price if intraday else last.close
    return last_price_now >= today_open * 1.005


def avg_daily_volume(history: list[DailyBar], *, window: int, exclude_last: bool = True) -> Optional[float]:
    relevant = history[:-1] if exclude_last else history
    relevant = relevant[-window:] if window else relevant
    if not relevant:
        return None
    return sum(bar.volume for bar in relevant) / len(relevant)


def realized_volume_ratio(history: list[DailyBar], intraday: list[IntradayBar]) -> Optional[float]:
    """今日实时量能与近 5 日均量的对比，用于放量突破判定。"""
    avg = avg_daily_volume(history, window=5)
    if not avg or avg <= 0:
        return None
    today_volume = sum(bar.volume for bar in intraday)
    return today_volume / avg


def limit_up_status(snapshot: MarketSnapshot, intraday: list[IntradayBar]) -> Optional[str]:
    """识别是否触及涨停：分时价格长时间停留在 +9.5% 以上视为封板。

    返回 ``sealed`` / ``touched`` / ``none``，无法判断时返回 None。
    """
    if not intraday:
        return None
    high_pct = max((bar.price / intraday[0].price - 1) * 100 for bar in intraday)
    if high_pct < 9.0:
        return "none"
    sealed_minutes = sum(1 for bar in intraday[-30:] if (bar.price / intraday[0].price - 1) * 100 >= 9.5)
    if sealed_minutes >= 15:
        return "sealed"
    return "touched"


def seal_order_trend(intraday: list[IntradayBar]) -> Optional[str]:
    """封单变化：尾盘最后 15 分钟相对前 15 分钟的量能变化。

    返回 ``rising`` / ``falling`` / ``stable``；数据不足时返回 None。
    """
    if len(intraday) < 30:
        return None
    tail = intraday[-15:]
    head = intraday[-30:-15]
    if not head or not tail:
        return None
    head_avg = sum(bar.volume for bar in head) / len(head)
    tail_avg = sum(bar.volume for bar in tail) / len(tail)
    if head_avg <= 0:
        return None
    ratio = tail_avg / head_avg
    if ratio >= 1.4:
        return "rising"
    if ratio <= 0.6:
        return "falling"
    return "stable"


def is_limit_up(price: float, prev_close: float) -> bool:
    if prev_close <= 0:
        return False
    return (price / prev_close - 1) * 100 >= 9.5


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def round2(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return round(value, 2)


def config_field_names(config_cls: type) -> list[str]:
    """返回 dataclass 字段名列表，便于把 dict 形式的覆盖安全地投影回 dataclass。"""
    return [f.name for f in fields(config_cls)]


def apply_overrides(config: Any, overrides: dict[str, Any] | None) -> Any:
    """在不修改原 config 的前提下，用 overrides（dict）覆盖同名字段。

    非法字段直接忽略，绝不抛错——避免外部脏数据把研究链路打挂。
    """
    if not overrides:
        return config
    allowed = set(config_field_names(type(config)))
    filtered = {k: v for k, v in overrides.items() if k in allowed}
    if not filtered:
        return config
    try:
        return replace(config, **filtered)
    except (TypeError, ValueError):
        return config


def config_to_dict(config: Any) -> dict[str, Any]:
    """把 dataclass 转成 dict 方便序列化为 JSON。"""
    return {f.name: getattr(config, f.name) for f in fields(type(config))}