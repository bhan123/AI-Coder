from datetime import datetime
from hashlib import sha256
import json
import sqlite3

import pytest

from app.models import PaperTrade
from app.repository import StrategyRepository
from app.review_center import ReviewCenter
from test_review_center import add_run


def trade(**updates):
    return PaperTrade(**dict(dict(code='000001', name='test', entry_price=10, exit_price=9.5,
                                 net_return_pct=-5.15, touched_breakeven=False,
                                 profitable_exit=False, exit_reason='stop_loss'), **updates))


def report(repo, as_of='2026-09-08T12:00:00+08:00'):
    return ReviewCenter(repo.db_path).report('fishing-reversal', '2026-09-04', '2026-09-04',
                                            as_of=datetime.fromisoformat(as_of))


def test_v1_joins_recorded_t1_by_first_run_without_changing_same_day_metrics(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'v1-first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    repo.save_t1_outcome('v1-first', '2026-09-07', trade())
    before = sha256(repo.db_path.read_bytes()).hexdigest()
    reviewed = report(repo)
    result = reviewed['events'][0]['t1_review']
    assert result['status'] == 'recorded_unverified'
    assert result['run_id'] == 'v1-first'
    assert result['recorded_outcome_date'] == '2026-09-07'
    assert result['rule_exit']['exit_price'] == 9.5
    assert result['next_trading_day_verified'] is False
    assert result['historical_visibility_verified'] is False
    assert reviewed['metrics']['close_positive_rate']['eligible_count'] == 0
    assert sha256(repo.db_path.read_bytes()).hexdigest() == before


def test_repeated_run_outcome_does_not_replace_first_signal_outcome(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    add_run(repo, 'later', '2026-09-04T14:51:00+08:00', strategy_id='fishing-reversal')
    repo.save_t1_outcome('later', '2026-09-07', trade())
    assert report(repo)['events'][0]['t1_review']['status'] == 'missing'


@pytest.mark.parametrize('as_of,status', [
    ('2026-09-04T16:00:00+08:00', 'not_yet_observable'),
    ('2026-09-07T10:29:59+08:00', 'not_yet_observable'),
    ('2026-09-07T02:30:00+00:00', 'recorded_unverified'),
])
def test_legacy_morning_result_is_not_visible_before_window_end(tmp_path, as_of, status):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    repo.save_t1_outcome('first', '2026-09-07', trade())
    result = report(repo, as_of)['events'][0]['t1_review']
    assert result['status'] == status
    if status == 'not_yet_observable':
        assert result['rule_exit'] is None
        assert result['recorded_outcome_date'] is None


@pytest.mark.parametrize('outcome_date,updates', [
    ('2026-09-04', {}), ('bad-date', {}),
    ('2026-09-07', {'entry_price': 11}), ('2026-09-07', {'exit_price': -1}),
    ('2026-09-07', {'exit_price': True}), ('2026-09-07', {'net_return_pct': float('nan')}),
    ('2026-09-07', {'code': '000002'}),
])
def test_invalid_legacy_record_stays_unknown_without_breaking_report(tmp_path, outcome_date, updates):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    raw = trade().model_dump(mode='json') | updates
    with sqlite3.connect(repo.db_path) as conn:
        conn.execute('INSERT INTO t1_outcomes VALUES (?, ?, ?, ?)',
                     ('first', '000001', outcome_date, json.dumps(raw)))
    result = report(repo)['events'][0]['t1_review']
    assert result['status'] == 'invalid_record'
    assert result['rule_exit'] is None


def test_v1_report_has_separate_t1_coverage_not_a_win_rate(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    repo.save_t1_outcome('first', '2026-09-07', trade())
    assert report(repo)['t1_summary'] == {
        'event_count': 1, 'recorded_unverified': 1, 'missing': 0,
        'invalid_record': 0, 'not_yet_observable': 0,
    }
