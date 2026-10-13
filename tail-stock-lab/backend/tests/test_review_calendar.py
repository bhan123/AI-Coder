from app.review_calendar import next_session
import pytest


def test_next_session_follows_published_exchange_holiday_schedule():
    result = next_session('000001', '2026-02-13')
    assert result['status'] == 'scheduled'
    assert result['next_date'] == '2026-02-24'
    assert result['exchange'] == 'SZSE'
    assert 'szse.cn' in result['source_reference']
    assert result['basis'] == 'published_exchange_schedule'
    assert result['actual_session_verified'] is False


@pytest.mark.parametrize('start,expected', [
    ('2026-01-05','2026-01-06'), ('2026-02-13','2026-02-24'),
    ('2026-04-03','2026-04-07'), ('2026-04-30','2026-05-06'),
    ('2026-06-18','2026-06-22'), ('2026-09-04','2026-09-07'),
    ('2026-09-24','2026-09-28'), ('2026-09-30','2026-10-08'),
    ('2026-10-09','2026-10-12'),
])
def test_published_schedule_handles_weekends_and_holidays_for_both_exchanges(start, expected):
    for code in ('600000', '300750'):
        assert next_session(code, start)['next_date'] == expected


@pytest.mark.parametrize('code,day,status', [
    ('000001','2026-05-09','signal_on_non_session'),
    ('000001','2026-09-20','signal_on_non_session'),
    ('000001','2026-01-01','signal_on_non_session'),
    ('000001','2025-12-31','outside_coverage'),
    ('000001','2026-12-31','outside_coverage'),
    ('920001','2026-09-04','unsupported_security'),
])
def test_uncovered_or_non_session_dates_do_not_invent_a_next_day(code, day, status):
    result = next_session(code, day)
    assert result['next_date'] is None
    assert result['status'] == status
