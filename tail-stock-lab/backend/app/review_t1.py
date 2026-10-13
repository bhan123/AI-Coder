"""Read legacy rule exits without treating them as verified next-day returns."""
from datetime import date, datetime, time
import json
from math import isfinite

from pydantic import ValidationError

from app.models import PaperTrade


def read_t1_review(conn, event, cutoff):
    result = {
        'status': 'missing', 'run_id': event['first_run_id'],
        'recorded_outcome_date': None, 'rule_exit': None,
        'next_trading_day_verified': False,
        'historical_visibility_verified': False,
        'limitations': ['交易日历未核验，记录日期不等于已确认的下一交易日。',
                        '旧记录没有采集入库时间，不能证明历史时点已可见。',
                        '规则退出为原规则模拟结果，不是次日收盘表现或实际交易收益。'],
    }
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='t1_outcomes'").fetchone():
        return result
    row = conn.execute('SELECT outcome_date, payload_json FROM t1_outcomes WHERE run_id=? AND code=?',
                       (event['first_run_id'], event['code'])).fetchone()
    if row is None:
        return result
    try:
        outcome_date = date.fromisoformat(row['outcome_date'])
        if outcome_date <= date.fromisoformat(event['date']):
            raise ValueError('outcome must follow recommendation')
        # Legacy exits have no exact exit timestamp. Do not expose a full morning
        # result before the entire 09:30-10:30 rule window has elapsed.
        if datetime.combine(outcome_date, time(10, 30), cutoff.tzinfo) > cutoff:
            result['status'] = 'not_yet_observable'
            return result
        payload = json.loads(row['payload_json'])
        if not isinstance(payload, dict) or any(
            not isinstance(payload.get(key), (int, float)) or isinstance(payload.get(key), bool)
            for key in ('entry_price', 'exit_price', 'net_return_pct')
        ):
            raise ValueError('non-numeric trade values')
        trade = PaperTrade.model_validate(payload)
        values = (trade.entry_price, trade.exit_price, trade.net_return_pct)
        if (trade.code != event['code'] or not all(isfinite(v) for v in values)
                or trade.entry_price <= 0 or trade.exit_price <= 0
                or not isinstance(event['first_price'], (int, float))
                or isinstance(event['first_price'], bool)
                or not isfinite(event['first_price']) or event['first_price'] <= 0
                or abs(trade.entry_price - event['first_price']) > 0.000001):
            raise ValueError('invalid or mismatched trade')
    except (ValueError, TypeError, ValidationError):
        result['status'] = 'invalid_record'
        return result
    result.update(status='recorded_unverified', recorded_outcome_date=outcome_date.isoformat(),
                  rule_exit={key: getattr(trade, key) for key in (
                      'entry_price', 'exit_price', 'net_return_pct', 'exit_reason')})
    return result
