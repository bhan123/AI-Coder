"""Project-wide Asia/Shanghai clock helpers.

SQLite's ``date('now')`` is UTC.  The crawler, scheduler and product UI use a
Shanghai business day, so deriving dates in Python keeps every layer aligned.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")


def business_now() -> datetime:
    """Return a naive Asia/Shanghai datetime for the existing SQLite schema."""
    return datetime.now(BUSINESS_TIMEZONE).replace(tzinfo=None)


def business_date() -> str:
    """Return the current business date as ``YYYY-MM-DD``."""
    return business_now().date().isoformat()
