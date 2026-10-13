"""历史回测：使用 Sina 全市场快照 + 日线 + Tencent 分时。

为避免 akshare/eastmoney 在某些网络下的不稳定，这里直接走公开 HTTP：
  - Sina 行情中心  : 当日全市场快照与日线
  - Tencent 行情   : 近 5 日分时

对每个交易日：
  1. 14:30 截面用当日收盘后的快照近似（实盘应使用盘中 tick）；
  2. 用 P1-P4 + V1 跑一遍，给出当日候选；
  3. 用次日日线评估 T+1 涨跌；
  4. 汇总到 CSV + 控制台摘要。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time as time_module
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import DailyBar, IntradayBar, MarketContext, MarketSnapshot, SectorQuote
from app.strategies import ALL_STRATEGIES
from app.strategies.base import Strategy


SINA_HEADERS = {"Referer": "https://finance.sina.com.cn/", "User-Agent": "Mozilla/5.0"}
TENCENT_HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class Candidate:
    strategy_id: str
    code: str
    name: str
    signal_at: str
    score: float
    entry_price: float
    next_open: float
    next_high: float
    next_low: float
    next_close: float
    best_gain_pct: float
    worst_drawdown_pct: float
    close_pct: float
    factors_summary: str
    # 多日退出
    t3_close_pct: float = 0.0
    t5_close_pct: float = 0.0
    t3_best_pct: float = 0.0
    t5_best_pct: float = 0.0


def _tencent_index_change() -> Optional[float]:
    """抓取上证综指当日涨跌幅。"""
    try:
        r = requests.get("https://qt.gtimg.cn/q=sh000001", headers=TENCENT_HEADERS, timeout=10)
        r.raise_for_status()
        fields = r.text.split('"')[1].split("~")
        return float(fields[32])
    except Exception:
        return None


def _historical_index_change(day: date) -> Optional[float]:
    """通过新浪 sh000001 日线拿到指定日期的指数涨跌幅。"""
    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        r = requests.get(url, params={"symbol": "sh000001", "scale": "240", "ma": "no", "datalen": "60"},
                         headers=SINA_HEADERS, timeout=10)
        r.raise_for_status()
        data = json.loads(r.text)
        if not isinstance(data, list):
            return None
        by_date = {bar["day"]: bar for bar in data}
        target = day.strftime("%Y-%m-%d")
        if target not in by_date:
            return None
        prev_close = _prev_close_from_index_list(data, target)
        if prev_close is None or prev_close <= 0:
            return None
        close = float(by_date[target]["close"])
        return (close - prev_close) / prev_close * 100
    except Exception:
        return None


def _prev_close_from_index_list(bars: list[dict], target: str) -> Optional[float]:
    sorted_bars = sorted(bars, key=lambda b: b["day"])
    prev_close: Optional[float] = None
    for bar in sorted_bars:
        if bar["day"] >= target:
            break
        try:
            prev_close = float(bar["close"])
        except (KeyError, ValueError, TypeError):
            continue
    return prev_close


def _sina_total_count() -> Optional[int]:
    try:
        r = requests.get(
            "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount?node=hs_a",
            headers=SINA_HEADERS, timeout=15,
        )
        r.raise_for_status()
        m = r.text.strip('"')
        return int(m)
    except Exception:
        return None


def fetch_sina_spot() -> list[dict]:
    """分页抓取全市场快照。"""
    total = _sina_total_count()
    if total is None:
        return []
    page_count = math.ceil(total / 80)
    items: list[dict] = []
    for page in range(1, page_count + 1):
        for retry in range(3):
            try:
                r = requests.get(
                    "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
                    params={"page": str(page), "num": "80", "sort": "symbol", "asc": "1",
                             "node": "hs_a", "symbol": "", "_s_r_a": "page"},
                    headers=SINA_HEADERS, timeout=15,
                )
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list):
                    items.extend(data)
                    break
            except Exception as exc:
                if retry == 2:
                    print(f"  [warn] 第 {page} 页拉取失败: {exc}", file=sys.stderr)
                time_module.sleep(1 + retry)
    return items


def fetch_sina_kline(code: str, datalen: int = 60) -> list[dict]:
    """日 K 线，datalen 越大越能拉更长历史。"""
    symbol = ("sh" if code.startswith(("5", "6", "7", "9")) else "sz") + code
    for retry in range(3):
        try:
            url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
            r = requests.get(url, params={"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(datalen)},
                             headers=SINA_HEADERS, timeout=10)
            r.raise_for_status()
            data = json.loads(r.text)
            if isinstance(data, list):
                return data
        except Exception:
            time_module.sleep(1 + retry)
    return []


def fetch_tencent_intraday(code: str) -> dict[str, list[dict]]:
    """返回 {YYYYMMDD: [bar, ...]}，最多 5 个交易日。"""
    symbol = ("sh" if code.startswith(("5", "6", "7", "9")) else "sz") + code
    for retry in range(3):
        try:
            r = requests.get(f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={symbol}",
                             headers=TENCENT_HEADERS, timeout=10)
            r.raise_for_status()
            payload = r.json()
            result: dict[str, list[dict]] = {}
            for day in payload.get("data", {}).get(symbol, {}).get("data", []):
                result[day["date"]] = []
                for bar in day.get("data", []):
                    parts = bar.split()
                    if len(parts) >= 2:
                        result[day["date"]].append({
                            "time": parts[0],
                            "price": float(parts[1]),
                            "volume": float(parts[3]) if len(parts) >= 4 else 0.0,
                        })
            return result
        except Exception:
            time_module.sleep(1 + retry)
    return {}


def fetch_tencent_limit_up_counts() -> dict[str, int]:
    """通过腾讯板块接口估算各板块涨停数；失败则返回空字典。"""
    try:
        r = requests.get("https://stock.gtimg.cn/data/index.php?appn=rank&t=ranka/chr&p=1&o=0&l=20&v=list_data",
                         headers=TENCENT_HEADERS, timeout=10)
        # 该接口不暴露板块聚合；这里不强行使用，返回空 dict 让策略在缺失数据时如实标记。
        return {}
    except Exception:
        return {}


EAST_MONEY_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


def fetch_stock_industry(code: str) -> Optional[str]:
    """返回东方财富给出的个股所属行业名（如"电气设备"）；失败返回 None。"""
    if not code or len(code) != 6:
        return None
    secid = ("1." if code.startswith(("5", "6", "7", "9")) else "0.") + code
    for retry in range(2):
        try:
            r = requests.get(
                "https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": secid, "fields": "f127,f161"},
                headers=EAST_MONEY_HEADERS, timeout=6,
            )
            r.raise_for_status()
            payload = r.json()
            data = payload.get("data") or {}
            industry = data.get("f127")
            if industry and isinstance(industry, str):
                return industry
            return None
        except Exception:
            time_module.sleep(0.3 + retry * 0.3)
    return None


def build_industry_sector_map(codes: list[str]) -> dict[str, str]:
    """对每只股票查一次行业，把行业名作为 sector 标识。失败时返回空字典，让 P1/P4 老实报 missing_data。"""
    industry_by_code: dict[str, str] = {}
    successes = 0
    for i, code in enumerate(sorted(codes)):
        industry = fetch_stock_industry(code)
        if industry:
            industry_by_code[code] = industry
            successes += 1
        if (i + 1) % 50 == 0:
            print(f"    行业 {i + 1}/{len(codes)}（命中 {successes}）")
    print(f"    行业映射最终命中 {successes}/{len(codes)}")
    return industry_by_code


def build_sector_map(codes: list[str]) -> dict[str, SectorQuote]:
    """简单按申万代码前缀猜板块；真正部署时应接 akshare 板块表。

    这里仅给出一个稳定的占位映射：返回 None 表示未知，避免假装有数据。
    """
    # 不假装板块归属，让 P1/P4 真实地标记为 missing_data。
    return {}


def parse_sina_row(row: dict, captured_at: datetime) -> Optional[MarketSnapshot]:
    try:
        code = str(row["code"]).zfill(6)
        name = str(row["name"])
        price = float(row["trade"])
        pct_change = float(row["changepercent"])
        day_low = float(row["low"])
        turnover_rate = float(row.get("turnoverratio", 0))
    except (KeyError, ValueError, TypeError):
        return None
    if price <= 0 or day_low <= 0:
        return None
    if name.startswith(("ST", "*ST", "N", "C")):
        return None
    volume_ratio = 0.0  # Sina 不直接给量比，留给后续 akshare 补；这里不影响 V1 主路径
    return MarketSnapshot(
        code=code,
        name=name,
        price=price,
        pct_change=pct_change,
        day_low=day_low,
        turnover_rate=turnover_rate,
        volume_ratio=volume_ratio,
        market_pct_change=0.0,  # 由调用方注入
        captured_at=captured_at,
    )


def _build_history_index(history_cache: dict[str, list[dict]]) -> dict[str, dict[date, dict]]:
    """构建 code -> {date: bar} 索引，方便按日期查找任意一天的 K 线。"""
    index: dict[str, dict[date, dict]] = {}
    for code, bars in history_cache.items():
        index[code] = {}
        for bar in bars:
            d = datetime.strptime(bar["day"], "%Y-%m-%d").date()
            index[code][d] = bar
    return index


def _previous_close(bars_by_date: dict[date, dict], day: date) -> Optional[float]:
    sorted_days = sorted(d for d in bars_by_date if d < day)
    if not sorted_days:
        return None
    try:
        return float(bars_by_date[sorted_days[-1]]["close"])
    except (KeyError, ValueError, TypeError):
        return None


def _build_intraday_index(intraday_cache: dict[str, dict[str, list[dict]]]) -> dict[str, dict[date, list[dict]]]:
    """构建 code -> {date: bars}，date 用 date 对象而不是 YYYYMMDD。"""
    index: dict[str, dict[date, list[dict]]] = {}
    for code, by_day in intraday_cache.items():
        index[code] = {}
        for day_str, bars in by_day.items():
            try:
                d = datetime.strptime(day_str, "%Y%m%d").date()
            except ValueError:
                continue
            index[code][d] = bars
    return index


def _snapshot_from_bar(code: str, bar: dict, prev_close: float, day: date,
                       *, turnover_rate: float = 2.0, volume_ratio: float = 1.5) -> Optional[MarketSnapshot]:
    if prev_close <= 0:
        return None
    pct_change = (bar["close"] - prev_close) / prev_close * 100
    captured_at = datetime.combine(day, time(14, 30), tzinfo=ZoneInfo("Asia/Shanghai"))
    return MarketSnapshot(
        code=code,
        name="",
        price=float(bar["close"]),
        pct_change=pct_change,
        day_low=float(bar["low"]),
        turnover_rate=turnover_rate,
        volume_ratio=volume_ratio,
        market_pct_change=0.0,
        captured_at=captured_at,
    )


def run_strategies_for_day(
    day: date,
    snapshots: list[MarketSnapshot],
    strategies: list[Strategy],
    history_cache: dict[str, list[dict]],
    intraday_cache: dict[str, dict[str, list[dict]]],
    industry_by_code: dict[str, str],
) -> list[Candidate]:
    """对一天跑所有策略，返回每个候选 + 次日真实涨跌。

    `industry_by_code` 是预查的 code -> 行业名映射；本函数基于当天 snapshots
    动态构造 sector_peers / sector_rank / sector_avg，让 P1 / P4 能基于当日
    全市场截面（虽然只是子集）做真实判定，而不是返回 missing_data。
    """
    intraday_index = _build_intraday_index(intraday_cache)

    # 按行业聚合：当日的"虚拟板块"
    sector_peers: dict[str, list[MarketSnapshot]] = {}
    sector_rank: dict[str, tuple[int, int]] = {}
    by_sector: dict[str, list[MarketSnapshot]] = {}
    sector_quotes: dict[str, SectorQuote] = {}
    for snap in snapshots:
        industry = industry_by_code.get(snap.code)
        if not industry:
            continue
        by_sector.setdefault(industry, []).append(snap)
    for industry, members in by_sector.items():
        avg_pct = sum(s.pct_change for s in members) / len(members)
        ordered = sorted(members, key=lambda s: s.pct_change, reverse=True)
        leader = ordered[0]
        sector_quotes[industry] = SectorQuote(
            code=industry,
            name=industry,
            pct_change=avg_pct,
            leader_code=leader.code,
            leader_name=leader.name,
            leader_pct_change=leader.pct_change,
            limit_up_count=sum(1 for s in members if s.pct_change >= 9.5),
        )
        for index, peer in enumerate(ordered, 1):
            sector_rank[peer.code] = (index, len(ordered))
        for peer in ordered:
            sector_peers[peer.code] = [p for p in ordered if p.code != peer.code]

    # 为缺失行业的股票构造 None quote，让 P1/P4 在没找到板块时如实报 missing_data
    sector_map: dict[str, SectorQuote] = sector_quotes

    candidates: list[Candidate] = []
    for strategy in strategies:
        for snap in snapshots:
            bars = history_cache.get(snap.code, [])
            intraday_bars_raw = intraday_index.get(snap.code, {}).get(day, [])

            daily_history = []
            for bar in bars:
                try:
                    bar_date = datetime.strptime(bar["day"], "%Y-%m-%d").date()
                except (KeyError, ValueError, TypeError):
                    continue
                if bar_date >= day:
                    continue
                try:
                    daily_history.append(DailyBar(
                        code=snap.code,
                        trade_date=bar_date,
                        open=float(bar["open"]),
                        high=float(bar["high"]),
                        low=float(bar["low"]),
                        close=float(bar["close"]),
                        volume=float(bar.get("volume", 0)),
                    ))
                except (KeyError, ValueError, TypeError):
                    continue

            intraday_bars = []
            for bar in intraday_bars_raw:
                m = _bar_minutes(bar["time"])
                if m is None:
                    continue
                intraday_bars.append(IntradayBar(
                    code=snap.code,
                    minutes_after_open=m,
                    price=bar["price"],
                    avg_price=bar["price"],
                    volume=bar["volume"],
                ))

            quote = sector_map.get(snap.code)
            rank_pair = sector_rank.get(snap.code, (None, None))

            context = MarketContext(
                snapshot=snap,
                daily_history=daily_history,
                intraday_bars=intraday_bars,
                sector=quote,
                sector_peers=sector_peers.get(snap.code, []),
                sector_rank=rank_pair[0],
                sector_total=rank_pair[1],
            )

            signal = strategy.evaluate_context(context)
            if not signal.eligible:
                continue

            next_bar = _find_next_trading_day(bars, day)
            if next_bar is None:
                continue

            try:
                entry_price = float(next_bar["open"])
                next_close = float(next_bar["close"])
                next_high = float(next_bar["high"])
                next_low = float(next_bar["low"])
            except (KeyError, ValueError, TypeError):
                continue

            factors_summary = " / ".join(
                f"{f.label}={f.value}" for f in signal.factors[:3]
            )

            candidates.append(Candidate(
                strategy_id=strategy.strategy_id,
                code=snap.code,
                name=snap.name,
                signal_at=snap.captured_at.isoformat(),
                score=signal.score,
                entry_price=entry_price,
                next_open=float(next_bar["open"]),
                next_high=next_high,
                next_low=next_low,
                next_close=next_close,
                best_gain_pct=(next_high - entry_price) / entry_price * 100,
                worst_drawdown_pct=(next_low - entry_price) / entry_price * 100,
                close_pct=(next_close - entry_price) / entry_price * 100,
                factors_summary=factors_summary,
            ))

            # T+3 / T+5：取接下来第 3、第 5 个交易日的收盘作为长持有期回报
            t3 = _find_nth_next_trading_day(bars, day, 3)
            t5 = _find_nth_next_trading_day(bars, day, 5)
            tail = candidates[-1]
            if t3 is not None:
                tail.t3_close_pct = (float(t3["close"]) - entry_price) / entry_price * 100
                tail.t3_best_pct = (
                    max(float(next_bar["high"]), float(t3["high"])) - entry_price
                ) / entry_price * 100
            if t5 is not None:
                tail.t5_close_pct = (float(t5["close"]) - entry_price) / entry_price * 100
                between_highs = [float(b["high"]) for b in _bars_between(bars, day, 5)]
                best_high = max(float(next_bar["high"]), max(between_highs) if between_highs else float(next_bar["high"]))
                tail.t5_best_pct = (best_high - entry_price) / entry_price * 100
    return candidates


def _bar_minutes(stamp: str) -> Optional[int]:
    """HHMM -> minutes_after_open (9:30=0)。"""
    try:
        hh, mm = int(stamp[:2]), int(stamp[2:])
    except (ValueError, TypeError):
        return None
    minutes = hh * 60 + mm
    open_minutes = 9 * 60 + 30
    if minutes < open_minutes or minutes > 15 * 60:
        return None
    if minutes <= 11 * 60 + 30:
        return minutes - open_minutes
    if minutes < 13 * 60:
        return 120
    return 120 + (minutes - 13 * 60)


def _find_next_trading_day(history: list[dict], signal_date: date) -> Optional[dict]:
    for row in history:
        row_date = datetime.strptime(row["day"], "%Y-%m-%d").date()
        if row_date > signal_date:
            return row
    return None


def _find_nth_next_trading_day(history: list[dict], signal_date: date, n: int) -> Optional[dict]:
    future = [r for r in history if datetime.strptime(r["day"], "%Y-%m-%d").date() > signal_date]
    future.sort(key=lambda r: r["day"])
    return future[n - 1] if len(future) >= n else None


def _bars_between(history: list[dict], signal_date: date, n: int) -> list[dict]:
    future = [r for r in history if datetime.strptime(r["day"], "%Y-%m-%d").date() > signal_date]
    future.sort(key=lambda r: r["day"])
    return future[:n]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=15, help="回测天数（交易日）")
    parser.add_argument("--csv", default="backtest_results.csv")
    args = parser.parse_args(argv)

    today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    trading_days = _recent_trading_days(today, args.days)
    print(f"回测窗口：{trading_days[0]} ~ {trading_days[-1]}（共 {len(trading_days)} 个交易日）")

    # 1. 抓取全市场近 30 个交易日的日 K 线
    print("\n抓取全市场日线…")
    market_change = _tencent_index_change() or 0.0
    print(f"  上证 {market_change:.2f}%")

    spot_rows = fetch_sina_spot()
    spot_map: dict[str, dict] = {}
    for row in spot_rows:
        try:
            code = str(row["code"]).zfill(6)
            if not code.startswith(("0", "3", "6")):
                continue
            name = str(row["name"])
            if name.startswith(("ST", "*ST", "N", "C")):
                continue
            spot_map[code] = row
        except (KeyError, TypeError):
            continue
    print(f"  可用股票 {len(spot_map)} 只")

    # 只对成交活跃的 top 股票做探测，避免无谓的网络调用
    sorted_by_turnover = sorted(
        spot_map.values(),
        key=lambda r: float(r.get("turnoverratio", 0)),
        reverse=True,
    )
    probe_codes = []
    seen: set[str] = set()
    for row in sorted_by_turnover:
        code = str(row["code"]).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        probe_codes.append(code)
        if len(probe_codes) >= 500:
            break

    print(f"  探测 top {len(probe_codes)} 只股票的近 30 日 K 线…")
    probe_history: dict[str, list[dict]] = {}
    for i, code in enumerate(probe_codes):
        probe_history[code] = fetch_sina_kline(code, datalen=30)
        if (i + 1) % 50 == 0:
            print(f"    {i + 1}/{len(probe_codes)}")

    # 选目标
    target_codes: set[str] = set()
    for code, bars in probe_history.items():
        by_date: dict[date, dict] = {}
        for b in bars:
            try:
                d = datetime.strptime(b["day"], "%Y-%m-%d").date()
                by_date[d] = {
                    "open": float(b["open"]),
                    "high": float(b["high"]),
                    "low": float(b["low"]),
                    "close": float(b["close"]),
                    "volume": float(b.get("volume", 0)),
                }
            except (KeyError, ValueError, TypeError):
                continue
        for d in trading_days:
            if d not in by_date:
                continue
            bar = by_date[d]
            prev = _previous_close(by_date, d)
            if prev is None or prev <= 0:
                continue
            pct = (bar["close"] - prev) / prev * 100
            if -7.0 <= pct <= -2.0 and bar["low"] > 0:
                rebound = (bar["close"] - bar["low"]) / bar["low"] * 100
                if rebound >= 0.7:
                    target_codes.add(code)
            if pct >= 9.5:
                target_codes.add(code)
    print(f"  命中候选形态: {len(target_codes)} 只")

    # 第三轮：拉这些股票的详细历史与近 5 日分时
    history_cache: dict[str, list[dict]] = {}
    intraday_cache: dict[str, dict[str, list[dict]]] = {}
    target_list = sorted(target_codes)
    for i, code in enumerate(target_list):
        history_cache[code] = fetch_sina_kline(code, datalen=40)
        intraday_cache[code] = fetch_tencent_intraday(code)
        if (i + 1) % 30 == 0:
            print(f"    详情 {i + 1}/{len(target_list)}")

    # 第四轮：拉行业归属，让 P1 / P4 也能基于行业聚合判定
    print("  拉取候选行业归属…")
    industry_by_code = build_industry_sector_map(target_list)
    print(f"  拿到 {len(industry_by_code)} 只的行业信息")

    all_results: list[Candidate] = []
    strategy_instances = [cls() for cls in ALL_STRATEGIES.values()]
    for day in trading_days:
        # 为这一天构建每只股票的"14:30 截面"
        day_snapshots: list[MarketSnapshot] = []
        # 取该日真实市场涨跌幅
        day_market_change = _historical_index_change(day)
        if day_market_change is None:
            day_market_change = market_change
        for code in target_list:
            bars = history_cache.get(code, [])
            by_date: dict[date, dict] = {}
            for b in bars:
                try:
                    d = datetime.strptime(b["day"], "%Y-%m-%d").date()
                    by_date[d] = {
                        "open": float(b["open"]),
                        "high": float(b["high"]),
                        "low": float(b["low"]),
                        "close": float(b["close"]),
                        "volume": float(b.get("volume", 0)),
                    }
                except (KeyError, ValueError, TypeError):
                    continue
            if day not in by_date:
                continue
            bar = by_date[day]
            prev_close = _previous_close(by_date, day) or bar["close"]
            snap = _snapshot_from_bar(code, bar, prev_close, day)
            if snap:
                snap.name = spot_map.get(code, {}).get("name", "")
                snap.market_pct_change = day_market_change
                # V1 还需要足够换手率，从当日 bar 推不出来；这里使用占位但保持可参与
                day_snapshots.append(snap)

        print(f"\n=== {day} 14:30 (候选池 {len(day_snapshots)} 只) ===")
        day_results = run_strategies_for_day(
            day,
            day_snapshots,
            strategy_instances,
            history_cache,
            intraday_cache,
            industry_by_code,
        )
        for cand in day_results:
            print(f"  [{cand.strategy_id}] {cand.code} {cand.name} score={cand.score:.1f} → "
                  f"次开 {cand.next_open} 次收 {cand.next_close} ({cand.close_pct:+.2f}%)")
            all_results.append(cand)

    _write_csv(args.csv, all_results)
    _print_summary(all_results)
    return 0


def _recent_trading_days(today: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = today
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _write_csv(path: str, results: list[Candidate]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow([
            "strategy_id", "code", "name", "signal_at", "score", "entry_price",
            "next_open", "next_high", "next_low", "next_close",
            "best_gain_pct", "worst_drawdown_pct", "close_pct",
            "t3_close_pct", "t3_best_pct", "t5_close_pct", "t5_best_pct",
            "factors_summary",
        ])
        for cand in results:
            writer.writerow([
                cand.strategy_id, cand.code, cand.name, cand.signal_at, cand.score, cand.entry_price,
                cand.next_open, cand.next_high, cand.next_low, cand.next_close,
                f"{cand.best_gain_pct:.2f}", f"{cand.worst_drawdown_pct:.2f}", f"{cand.close_pct:.2f}",
                f"{cand.t3_close_pct:.2f}", f"{cand.t3_best_pct:.2f}",
                f"{cand.t5_close_pct:.2f}", f"{cand.t5_best_pct:.2f}",
                cand.factors_summary,
            ])
    print(f"\n结果已写入 {path}（共 {len(results)} 行）")


def _sharpe(values: list[float]) -> float:
    """年化夏普（按 T+1 频次，不严格换算）。"""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    return mean / std if std > 0 else 0.0


def _max_drawdown(values: list[float]) -> float:
    """累计净值序列的最大回撤。values 是每笔的收益率（%），我们以 1 + v/100 累乘。"""
    if not values:
        return 0.0
    nav = 1.0
    peak = 1.0
    worst = 0.0
    for v in values:
        nav *= (1.0 + v / 100.0)
        peak = max(peak, nav)
        worst = min(worst, (nav - peak) / peak)
    return worst * 100


def _print_summary(results: list[Candidate]) -> None:
    if not results:
        print("\n没有命中候选，无法给出结论。")
        return

    by_strategy: dict[str, list[Candidate]] = {}
    for cand in results:
        by_strategy.setdefault(cand.strategy_id, []).append(cand)

    print("\n===== 初步结论 =====")
    overall = results
    touched_breakeven = sum(1 for c in overall if c.best_gain_pct > 0.15)
    profitable_close = sum(1 for c in overall if c.close_pct > 0)
    t3_available = [c for c in overall if c.t3_close_pct != 0.0 or c.t3_best_pct != 0.0]
    t5_available = [c for c in overall if c.t5_close_pct != 0.0 or c.t5_best_pct != 0.0]
    # 只有同时有 t3_close / t3_best 不为零（找到了 t3 那天）的才算真正可用
    t3_real = [c for c in overall if any(b.get("day") for b in []) or c.t3_best_pct != 0.0]
    t5_real = [c for c in overall if c.t5_best_pct != 0.0]

    avg_close = sum(c.close_pct for c in overall) / len(overall)
    avg_best = sum(c.best_gain_pct for c in overall) / len(overall)
    avg_worst = sum(c.worst_drawdown_pct for c in overall) / len(overall)

    closes = [c.close_pct for c in overall]
    sharpe = _sharpe(closes)
    mdd = _max_drawdown(closes)

    print(f"总体：{len(overall)} 个候选信号")
    print(f"  T+1 触及盈亏平衡率（最高价 > 入场价 + 0.15% 成本）：{touched_breakeven/len(overall)*100:.1f}%")
    print(f"  T+1 收盘上涨率：{profitable_close/len(overall)*100:.1f}%")
    print(f"  T+1 收盘涨跌幅均值：{avg_close:.2f}%  夏普：{sharpe:.2f}  最大回撤：{mdd:.2f}%")
    print(f"  T+1 最大涨幅均值：{avg_best:.2f}%")
    print(f"  T+1 最大回撤均值：{avg_worst:.2f}%")
    if t3_available:
        t3_profitable = sum(1 for c in t3_available if c.t3_close_pct > 0)
        avg_t3 = sum(c.t3_close_pct for c in t3_available) / len(t3_available)
        print(f"  T+3 收盘上涨率（{len(t3_available)} 个有数据）：{t3_profitable/len(t3_available)*100:.1f}%  均值 {avg_t3:.2f}%")
    else:
        print("  T+3：无足够历史计算")
    if t5_available:
        t5_profitable = sum(1 for c in t5_available if c.t5_close_pct > 0)
        avg_t5 = sum(c.t5_close_pct for c in t5_available) / len(t5_available)
        print(f"  T+5 收盘上涨率（{len(t5_available)} 个有数据）：{t5_profitable/len(t5_available)*100:.1f}%  均值 {avg_t5:.2f}%")
    else:
        print("  T+5：无足够历史计算")

    print("\n按策略拆分：")
    for sid, cands in by_strategy.items():
        touch = sum(1 for c in cands if c.best_gain_pct > 0.15) / len(cands) * 100
        up = sum(1 for c in cands if c.close_pct > 0) / len(cands) * 100
        t3_up_count = sum(1 for c in cands if c.t3_best_pct != 0.0 and c.t3_close_pct > 0)
        t3_n = sum(1 for c in cands if c.t3_best_pct != 0.0)
        avg = sum(c.close_pct for c in cands) / len(cands)
        sharpe = _sharpe([c.close_pct for c in cands])
        mdd = _max_drawdown([c.close_pct for c in cands])
        print(
            f"  {sid}: n={len(cands)} T+1触及={touch:.1f}% 收盘上涨={up:.1f}% 均值={avg:.2f}% "
            f"夏普={sharpe:.2f} 回撤={mdd:.2f}% T+3:{t3_up_count}/{t3_n}"
        )

    # 按 score 分桶
    print("\n按 T+1 评分分桶：")
    buckets = [(">=70", [c for c in overall if c.score >= 70]),
                ("65-70", [c for c in overall if 65 <= c.score < 70]),
                ("<65", [c for c in overall if c.score < 65])]
    for label, cands in buckets:
        if not cands:
            continue
        avg = sum(c.close_pct for c in cands) / len(cands)
        up = sum(1 for c in cands if c.close_pct > 0) / len(cands) * 100
        print(f"  score {label}: n={len(cands)} 收盘上涨={up:.1f}% 均值={avg:.2f}%")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))