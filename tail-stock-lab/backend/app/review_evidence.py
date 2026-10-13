"""Unadjusted closing evidence supplied by a separately verified data adapter.

Schema validation checks consistency, not a vendor's authenticity. No board
limit is guessed from a stock code and no daily high invents a touch timestamp.
"""
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ClosingEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str = Field(pattern=r"^\d{6}$")
    trade_date: date
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    limit_up: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    day_high: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    source: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    price_at: datetime
    fetched_at: datetime
    fetch_started_at: datetime | None = None
    price_time_basis: Literal["source_timestamp", "daily_session_end"] = "source_timestamp"
    source_payload: dict | None = None
    price_basis: Literal["unadjusted"] = "unadjusted"
    limit_touch_times: tuple[datetime, ...] = ()

    @model_validator(mode="after")
    def validate_session(self):
        if self.price_at.tzinfo is None or self.fetched_at.tzinfo is None:
            raise ValueError("evidence timestamps require timezone")
        close_at = self.price_at.astimezone(SHANGHAI)
        if close_at.date() != self.trade_date or close_at.time() != time(15, 0):
            raise ValueError("expected regular session closing timestamp")
        if self.fetched_at < self.price_at:
            raise ValueError("evidence cannot be fetched before close")
        if self.fetch_started_at is not None:
            if self.fetch_started_at.tzinfo is None or self.fetch_started_at > self.fetched_at:
                raise ValueError("fetch start must be aware and not after completion")
        if self.day_high is not None and self.day_high < self.close:
            raise ValueError("daily high below close")
        if self.limit_up is not None and max(self.close, self.day_high or self.close) > self.limit_up:
            raise ValueError("price exceeds supplied limit")
        for touched in self.limit_touch_times:
            if touched.tzinfo is None or touched.astimezone(SHANGHAI).date() != self.trade_date:
                raise ValueError("touch timestamp must identify the same session")
            if touched > self.price_at or touched.astimezone(SHANGHAI).time() < time(9, 30):
                raise ValueError("touch timestamp outside regular session")
            if time(11, 30) < touched.astimezone(SHANGHAI).time() < time(13):
                raise ValueError("touch timestamp during lunch break")
            if self.limit_up is None or (self.day_high is not None and self.day_high != self.limit_up):
                raise ValueError("touch contradicts daily high or missing limit price")
        return self


def evaluate_close(event: dict, quote: ClosingEvidence) -> dict:
    quote = ClosingEvidence.model_validate(quote.model_dump())
    if event["code"] != quote.code or event["date"] != quote.trade_date.isoformat():
        raise ValueError("closing evidence belongs to a different security/session")
    first_at = datetime.fromisoformat(event["first_at"])
    if first_at.tzinfo is None:
        first_at = first_at.replace(tzinfo=SHANGHAI)
    result = {
        "close_positive": None,
        "close_limit": quote.close == quote.limit_up if quote.limit_up else None,
        "close_return_pct": None,
        "post_alert_limit": None,
        "quality_flags": [],
    }
    if first_at >= quote.price_at:
        result["quality_flags"].append("signal_not_before_close")
        return result
    try:
        first = Decimal(str(event["first_price"]))
        valid_first = first.is_finite() and first > 0
    except InvalidOperation:
        valid_first = False
    if valid_first:
        result["close_positive"] = quote.close > first
        result["close_return_pct"] = round(float((quote.close / first - 1) * 100), 4)
    else:
        result["quality_flags"].append("invalid_first_price")
    if quote.limit_up is None:
        result["quality_flags"].append("limit_price_unknown")
    elif result["close_limit"] or any(touched > first_at for touched in quote.limit_touch_times):
        result["post_alert_limit"] = True
    elif quote.day_high is not None and quote.day_high < quote.limit_up:
        result["post_alert_limit"] = False
    else:
        result["quality_flags"].append("touch_order_unknown")
    return result
