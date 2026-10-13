from __future__ import annotations

from datetime import datetime

import requests

from app.backtest import simulate_t1_exit
from app.models import NextDayPath, PaperTrade, Signal, T1MarketReview, T1PricePoint
from app.repository import StrategyRepository


class TencentT1PathProvider:
    """Fetch the next available trading day's minute path for a stored signal."""

    source_name = "Tencent minute path"

    @staticmethod
    def _symbol(code: str) -> str:
        return ("sh" if code.startswith("6") else "sz") + code

    @staticmethod
    def _next_day(signal: Signal, payload: dict) -> dict | None:
        try:
            days = payload["data"][TencentT1PathProvider._symbol(signal.code)]["data"]
        except KeyError as exc:
            raise RuntimeError(f"Tencent minute data is missing {signal.code}") from exc
        signal_date = signal.snapshot.captured_at.date()
        next_days = [day for day in days if datetime.strptime(day["date"], "%Y%m%d").date() > signal_date]
        if not next_days:
            return None
        return min(next_days, key=lambda item: item["date"])

    @staticmethod
    def _points(day: dict, end_time: str) -> list[T1PricePoint]:
        points: list[T1PricePoint] = []
        for bar in day["data"]:
            parts = bar.split()
            if len(parts) >= 2 and "0930" <= parts[0] <= end_time:
                try:
                    points.append(T1PricePoint(time=parts[0], price=float(parts[1])))
                except ValueError:
                    continue
        return points

    @staticmethod
    def parse_next_path(signal: Signal, payload: dict) -> NextDayPath | None:
        day = TencentT1PathProvider._next_day(signal, payload)
        if day is None:
            return None
        points = TencentT1PathProvider._points(day, "1030")
        prices = [point.price for point in points]
        if not prices:
            return None
        return NextDayPath(
            code=signal.code,
            entry_price=signal.snapshot.price,
            prices=prices,
            observed_at=datetime.strptime(day["date"], "%Y%m%d"),
        )

    @staticmethod
    def parse_review(signal: Signal, payload: dict) -> T1MarketReview | None:
        day = TencentT1PathProvider._next_day(signal, payload)
        if day is None:
            return None
        points = TencentT1PathProvider._points(day, "1450")
        if not points:
            return None
        observed_at = datetime.strptime(
            f"{day['date']} {points[-1].time}", "%Y%m%d %H%M"
        )
        prices = [point.price for point in points]
        return T1MarketReview(
            observed_at=observed_at,
            open_price=points[0].price,
            high_price=max(prices),
            low_price=min(prices),
            last_price=points[-1].price,
            points=points,
        )

    def _fetch_payload(self, signal: Signal) -> dict:
        response = requests.get(
            f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={self._symbol(signal.code)}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def fetch(self, signal: Signal) -> NextDayPath | None:
        return self.parse_next_path(signal, self._fetch_payload(signal))

    def fetch_review(self, signal: Signal) -> T1MarketReview | None:
        return self.parse_review(signal, self._fetch_payload(signal))


class T1OutcomeCollector:
    def __init__(self, repository: StrategyRepository, provider: TencentT1PathProvider | None = None) -> None:
        self.repository = repository
        self.provider = provider or TencentT1PathProvider()

    def collect_due(self, as_of: datetime | None = None) -> list[PaperTrade]:
        as_of = as_of or datetime.now()
        trades: list[PaperTrade] = []
        for run_id, signal in self.repository.pending_t1_signals(as_of.date().isoformat()):
            path = self.provider.fetch(signal)
            if path is None:
                continue
            trade = simulate_t1_exit(signal, path)
            self.repository.save_t1_outcome(run_id, path.observed_at.date().isoformat(), trade)
            trades.append(trade)
        return trades


class T1ReviewCollector:
    """Attach the observed 14:50 next-day chart without changing the exit rule."""

    def __init__(self, repository: StrategyRepository, provider: TencentT1PathProvider | None = None) -> None:
        self.repository = repository
        self.provider = provider or TencentT1PathProvider()

    def collect_due(self, as_of: datetime | None = None) -> list[PaperTrade]:
        as_of = as_of or datetime.now()
        reviews: list[PaperTrade] = []
        for run_id, signal, trade in self.repository.t1_outcomes_due_for_review(as_of.date().isoformat()):
            try:
                market_review = self.provider.fetch_review(signal)
            except Exception as exc:
                print(f"T+1 market review unavailable code={signal.code} error={exc}")
                continue
            if market_review is None:
                continue
            reviewed_trade = trade.model_copy(update={"market_review": market_review})
            self.repository.save_t1_outcome(run_id, as_of.date().isoformat(), reviewed_trade)
            reviews.append(reviewed_trade)
        return reviews
