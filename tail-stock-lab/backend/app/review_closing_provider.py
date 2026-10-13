"""Bounded, unadjusted daily bars; no inferred limit prices or touch times.

Reference: AKShare stock_zh_a_hist_tx (Tencent newfqkline endpoint).
Unlike its adjusted-series fallback, only the explicit `day` series is accepted.
The bar date identifies a session, not a vendor-provided intraday timestamp.
"""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re
from urllib.parse import urlencode

import requests

from app.review_evidence import ClosingEvidence, SHANGHAI


class TencentClosingProvider:
    source_name = "tencent-unadjusted-daily-v1"
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

    def __init__(self, *, session=None, clock=None):
        self.session = session or requests.Session()
        self.clock = clock or (lambda: datetime.now(SHANGHAI))

    def fetch(self, code: str, trade_date: date) -> ClosingEvidence:
        started = self.clock()
        if started.tzinfo is None:
            raise ValueError("fetch clock must include timezone")
        if not re.fullmatch(r"(?:000|001|002|003|300|301|600|601|603|605|688)[0-9]{3}", code):
            raise ValueError("unsupported security: only declared Shanghai/Shenzhen A-share prefixes")
        # Operational delay, not a guarantee of vendor publication completeness.
        if started < datetime.combine(trade_date, time(16), SHANGHAI):
            raise ValueError("closing bar not ready: fetch from 16:00 Shanghai time")
        symbol = ("sh" if code.startswith("6") else "sz") + code
        day = trade_date.isoformat()
        params = {"param": f"{symbol},day,{day},{day},2,"}
        response = self.session.get(self.url, params=params, timeout=(5, 15))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise ValueError("vendor returned an unsuccessful response")
        try:
            rows = payload["data"][symbol]["day"]
            matches = [row for row in rows if isinstance(row, list) and len(row) >= 6 and row[0] == day]
        except (KeyError, TypeError) as exc:
            raise ValueError("missing security or explicit unadjusted daily series") from exc
        if len(matches) != 1:
            raise ValueError("expected exactly one bar for requested session")
        row = matches[0]
        try:
            opened, closed, high, low, volume = [Decimal(str(value)) for value in row[1:6]]
            if not all(value.is_finite() and value > 0 for value in (opened, closed, high, low, volume)):
                raise ValueError("nonpositive/nonfinite OHLC or volume")
            if not low <= min(opened, closed) <= max(opened, closed) <= high:
                raise ValueError("inconsistent daily OHLC")
        except InvalidOperation as exc:
            raise ValueError("invalid daily prices") from exc
        raw = {"symbol": symbol, "day": row}
        digest = sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        return ClosingEvidence(
            code=code, trade_date=trade_date, close=row[2], day_high=row[3],
            source=self.source_name,
            source_reference=self.url + "?" + urlencode(params) + "#sha256=" + digest,
            price_at=datetime.combine(trade_date, time(15), SHANGHAI),
            price_time_basis="daily_session_end", source_payload=raw,
            fetch_started_at=started, fetched_at=self.clock(),
        )
