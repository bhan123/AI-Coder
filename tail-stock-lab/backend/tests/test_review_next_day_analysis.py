from datetime import datetime
from hashlib import sha256

import pytest

from app.review_evidence_store import ClosingEvidenceStore
from test_review_next_day import NOW, close_quote, report, setup_event


def test_next_day_decline_analysis_links_evidence_and_keeps_signal_day_independent(tmp_path):
    repo = setup_event(tmp_path)
    before = sha256(repo.db_path.read_bytes()).hexdigest()
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    same_day_id = store.record(close_quote('2026-09-04', close=10.2))
    next_day_id = store.record(close_quote(close=8.8, day_high=10.5))
    result = report(repo)
    event = result['events'][0]
    analysis = event['next_day_analysis']
    assert analysis['target_date'] == '2026-09-07'
    assert analysis['outcome']['assessment'] == 'below_first'
    assert analysis['outcome']['return_pct'] == -12
    assert analysis['trigger']['run_id'] == 'first'
    assert analysis['trigger']['reason'] == '测试信号'
    assert event['analysis']['outcome']['return_pct'] == 2
    assert analysis['causality'] == 'unverified'
    facts = {fact['key']: fact for fact in analysis['facts']}
    assert facts['next_close_vs_reference']['evidence_ids'] == [next_day_id]
    assert set(facts['next_close_vs_signal_close']['evidence_ids']) == {same_day_id, next_day_id}
    assert facts['next_close_vs_signal_close']['value_pct'] == pytest.approx(-13.7255)
    patterns = {item['key'] for item in analysis['patterns']}
    assert 'rebound_not_held' in patterns
    assert 'closed_below_signal_low' in patterns
    assert analysis['hypotheses'] and all(item['status'] == 'needs_evidence' for item in analysis['hypotheses'])
    assert sha256(repo.db_path.read_bytes()).hexdigest() == before


def test_below_recommendation_but_above_previous_close_is_not_called_a_down_session(tmp_path):
    repo = setup_event(tmp_path)
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    store.record(close_quote('2026-09-04', close=8))
    store.record(close_quote(close=9, day_high=9.5))
    analysis = report(repo)['events'][0]['next_day_analysis']
    assert analysis['outcome']['return_pct'] == -10
    assert analysis['outcome']['session_return_pct'] == 12.5
    assert '低于推荐价，但高于推荐日收盘' in analysis['conclusion']
    assert 'reference_loss_but_session_gain' in {item['key'] for item in analysis['patterns']}
    assert 'no_recovery_above_reference' in {item['key'] for item in analysis['patterns']}


def test_next_session_decline_above_reference_is_explicit_without_faking_a_reference_loss(tmp_path):
    repo = setup_event(tmp_path)
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    store.record(close_quote('2026-09-04', close=12, day_high=12))
    store.record(close_quote(close=11, day_high=11.5))
    analysis = report(repo)['events'][0]['next_day_analysis']
    assert analysis['outcome']['assessment'] == 'above_first'
    assert analysis['outcome']['session_return_pct'] == pytest.approx(-8.3333)
    assert '仍高于推荐价，但低于推荐日收盘' in analysis['conclusion']
    assert 'session_decline_above_reference' in {item['key'] for item in analysis['patterns']}
    assert analysis['hypotheses']


def test_reports_summarize_next_day_diagnostics_separately_and_keep_old_revision(tmp_path):
    from app.review_reports import ReviewReportArchive
    repo = setup_event(tmp_path)
    archive = ReviewReportArchive(tmp_path / 'reports.db')
    initial = archive.save(report(repo), period='daily')
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    store.record(close_quote(close=8.8, day_high=9.8))
    result = report(repo)
    summary = result['next_day_analysis_summary']
    assert summary['event_count'] == 1
    assert summary['below_reference_count'] == 1
    assert summary['session_decline_count'] == 0
    assert summary['session_unknown_count'] == 1
    assert summary['unknown_count'] == 0
    assert summary['unresolved_cause_count'] == 1
    assert summary['confirmed_cause_count'] == 0
    assert {row['key'] for row in summary['patterns']} == {'closed_below_signal_low', 'no_recovery_above_reference'}
    assert result['review_summary']['close_down_count'] == 0
    latest = archive.save(result, period='daily')
    assert latest['revision'] == initial['revision'] + 1
    assert archive.get(initial['report_id'])['report']['events'][0]['next_day_analysis']['outcome']['assessment'] == 'unknown'
    assert archive.get(latest['report_id'])['report']['next_day_analysis_summary'] == summary
    assert archive.save(report(repo), period='daily')['report_id'] == latest['report_id']


@pytest.mark.parametrize('case', ['missing', 'before_close', 'before_receipt', 'wrong_date', 'conflict'])
def test_unknown_next_day_outcome_never_borrows_signal_day_prices_or_invents_causes(tmp_path, case):
    from test_review_center import add_run
    repo = setup_event(tmp_path)
    add_run(repo, 'late', '2026-09-04T14:59:00+08:00', strategy_id='fishing-reversal', price=8)
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    cutoff = NOW
    if case in {'before_close', 'before_receipt', 'conflict'}:
        store.record(close_quote(close=8.8))
    if case == 'before_close':
        cutoff = datetime.fromisoformat('2026-09-07T06:59:00+00:00')
    elif case == 'before_receipt':
        cutoff = datetime.fromisoformat('2026-09-07T08:29:59+00:00')
    elif case == 'wrong_date':
        store.record(close_quote('2026-09-04', close=8.8))
    elif case == 'conflict':
        store.record(close_quote(close=9, source='different-test-source'))
    result = report(repo, cutoff)
    analysis = result['events'][0]['next_day_analysis']
    assert analysis['outcome']['assessment'] == 'unknown'
    assert analysis['facts'] == []
    assert analysis['patterns'] == []
    assert analysis['hypotheses'] == []
    assert result['next_day_analysis_summary']['unknown_count'] == 1


def test_negative_legacy_rule_and_signal_day_do_not_invent_a_next_day_decline(tmp_path):
    from test_review_t1 import trade
    from test_review_center import add_run
    repo = setup_event(tmp_path)
    add_run(repo, 'late', '2026-09-04T14:59:00+08:00', strategy_id='fishing-reversal', price=9)
    repo.save_t1_outcome('first', '2026-09-07', trade())
    ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW).record(close_quote(close=11))
    event = report(repo)['events'][0]
    assert event['t1_review']['rule_exit']['net_return_pct'] < 0
    assert event['analysis']['outcome']['return_pct'] < 0
    assert event['next_day_analysis']['outcome']['assessment'] == 'above_first'
    assert event['next_day_analysis']['hypotheses'] == []
    assert event['next_day_analysis']['patterns'] == []


def test_conflicting_signal_close_does_not_hide_valid_next_close_or_invent_session_decline(tmp_path):
    repo = setup_event(tmp_path)
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    store.record(close_quote('2026-09-04', close=10))
    store.record(close_quote('2026-09-04', close=9, source='different-test-source'))
    store.record(close_quote(close=9.5, day_high=None))
    analysis = report(repo)['events'][0]['next_day_analysis']
    assert analysis['outcome']['assessment'] == 'below_first'
    assert analysis['outcome']['session_return_pct'] is None
    assert not analysis['patterns']
    gaps = {item['key'] for item in analysis['data_gaps']}
    assert {'signal_close_unavailable', 'next_high_unavailable', 'corporate_actions_unverified'} <= gaps


def test_next_day_analysis_is_exposed_by_read_only_api_only_for_v1(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main
    from test_review_center import add_run
    repo = setup_event(tmp_path)
    add_run(repo, 'alert', '2026-09-04T10:00:00+08:00')
    monkeypatch.setattr(main, 'repository', repo)
    before = sha256(repo.db_path.read_bytes()).hexdigest()
    client = TestClient(main.app)
    v1 = client.get('/api/review/summary', params={'strategy_id': 'fishing-reversal', 'date_from': '2026-09-04', 'date_to': '2026-09-04'}).json()
    alert = client.get('/api/review/summary', params={'strategy_id': 'limit-up-ambush', 'date_from': '2026-09-04', 'date_to': '2026-09-04'}).json()
    assert v1['events'][0]['next_day_analysis']['outcome']['assessment'] == 'unknown'
    assert 'next_day_analysis' not in alert['events'][0]
    assert alert['next_day_analysis_summary'] is None
    assert sha256(repo.db_path.read_bytes()).hexdigest() == before


def test_small_decline_is_not_classified_as_flat_after_percent_rounding(tmp_path):
    from app.repository import StrategyRepository
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal', price=100000)
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    store.record(close_quote('2026-09-04', close=100000, day_high=100000))
    store.record(close_quote(close=99999.99, day_high=100000))
    result = report(repo)
    analysis = result['events'][0]['next_day_analysis']
    assert analysis['outcome']['return_pct'] == 0  # rounded display value, not a flat-price verdict
    assert analysis['outcome']['assessment'] == 'below_first'
    assert analysis['outcome']['session_assessment'] == 'down'
    assert result['next_day_analysis_summary']['below_reference_count'] == 1
    assert result['next_day_analysis_summary']['session_decline_count'] == 1
