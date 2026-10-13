"""Next scheduled session's market close, separate from simulated rule exits."""
from datetime import datetime, time, date

from app.review_calendar import next_session
from app.review_evidence import ClosingEvidence, SHANGHAI, evaluate_close


def next_day_close(event, evidence_store, cutoff):
    calendar = next_session(event['code'], event['date'])
    result = {'calendar': calendar, 'status': 'calendar_unknown',
              'close_return_pct': None, 'close_positive': None, 'closing_evidence': None,
              'rule_date_matches_schedule': None,
              'limitations': ['比较下一计划交易日收盘与首次参考价，不是模拟净收益或实际交易收益。',
                              '使用已公布休市安排，不代表已核验临时休市、个股停牌及历史发布可见性。']}
    if calendar['status'] != 'scheduled':
        return result
    target = calendar['next_date']
    rule_day = event.get('t1_review', {}).get('recorded_outcome_date')
    if rule_day:
        result['rule_date_matches_schedule'] = rule_day == target
    if cutoff < datetime.combine(date.fromisoformat(target), time(15), SHANGHAI):
        return result | {'status': 'not_yet_closed'}
    record = evidence_store.latest(event['code'], target, as_of=cutoff)
    if record is None:
        return result | {'status': 'pending_close'}
    result['closing_evidence'] = record
    if record.get('conflict'):
        return result | {'status': 'closing_source_conflict'}
    outcome = evaluate_close(event | {'date': target}, ClosingEvidence.model_validate(record['quote']))
    return result | {'status': 'close_available' if outcome['close_return_pct'] is not None else 'invalid_first_price',
                     'close_return_pct': outcome['close_return_pct'], 'close_positive': outcome['close_positive']}
