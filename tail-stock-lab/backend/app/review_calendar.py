"""Versioned published exchange schedule, not a live suspension calendar.

2026 holidays transcribed from the two exchange notices referenced below,
checked 2026-09-09. Never extrapolate into an uncovered year or use a stock's
next available bar to infer the next market session.
"""
from datetime import date, timedelta
import re


VERSION = 'cn-a-2026-published-v1'
SOURCES = {
    'SSE': 'https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml',
    'SZSE': 'https://investor.szse.cn/disclosure/notice/general/t20251222_618087.html',
}
HOLIDAYS = tuple((date.fromisoformat(start), date.fromisoformat(end)) for start, end in (
    ('2026-01-01', '2026-01-03'), ('2026-02-15', '2026-02-23'),
    ('2026-04-04', '2026-04-06'), ('2026-05-01', '2026-05-05'),
    ('2026-06-19', '2026-06-21'), ('2026-09-25', '2026-09-27'),
    ('2026-10-01', '2026-10-07'),
))


def next_session(code: str, signal_date: str) -> dict:
    result = {'status': 'outside_coverage', 'next_date': None, 'exchange': None,
              'basis': 'published_exchange_schedule', 'version': VERSION,
              'source_reference': None, 'published_on': '2025-12-22', 'checked_on': '2026-09-09',
              'actual_session_verified': False,
              'limitations': ['仅覆盖2026年沪深A股已公布常规交易安排，不含临时休市或个股停牌确认。']}
    if not isinstance(code, str) or not re.fullmatch(r'(?:000|001|002|003|300|301|600|601|603|605|688)[0-9]{3}', code):
        return result | {'status': 'unsupported_security'}
    exchange = 'SSE' if code.startswith('6') else 'SZSE'
    result.update(exchange=exchange, source_reference=SOURCES[exchange])
    day = date.fromisoformat(signal_date)
    if day.year != 2026:
        return result

    def is_open(value):
        return value.weekday() < 5 and not any(start <= value <= end for start, end in HOLIDAYS)

    if not is_open(day):
        return result | {'status': 'signal_on_non_session'}
    day += timedelta(days=1)
    while day.year == 2026:
        if is_open(day):
            return result | {'status': 'scheduled', 'next_date': day.isoformat()}
        day += timedelta(days=1)
    return result
