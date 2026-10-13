from app.repository import StrategyRepository
from app.review_center import ReviewCenter
from test_review_center import add_run
from app.review_evidence_store import ClosingEvidenceStore
from test_review_evidence import evidence
import pytest


@pytest.mark.parametrize('sample_at', ['2026-09-04T15:00:00+08:00', '2026-09-04T15:05:00+08:00', '2026-09-04T07:05:00+00:00'])
def test_after_close_samples_cannot_explain_an_earlier_close_as_gain_reversal(tmp_path, sample_at):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    add_run(repo, 'late_sample', sample_at, price=11)
    ClosingEvidenceStore(tmp_path / 'review_evidence.db').record(evidence(close='9.00'))
    report = ReviewCenter(repo.db_path).report('limit-up-ambush', '2026-09-04', '2026-09-04')
    analysis = report['events'][0]['analysis']
    assert analysis['outcome']['basis'] == 'close'
    assert report['events'][0]['post_signal_path']['sample_count'] == 0
    assert not any(fact.get('pattern') == 'sampled_gain_reversed' for fact in analysis['facts'])


def test_analysis_preserves_trigger_and_does_not_invent_decline_causes(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    add_run(repo, 'later', '2026-09-04T14:00:00+08:00', price=9)
    report = ReviewCenter(repo.db_path).report('limit-up-ambush', '2026-09-04', '2026-09-04')
    analysis = report['events'][0]['analysis']
    assert analysis['trigger']['reason'] == '测试信号'
    assert analysis['trigger']['run_id'] == 'first'
    assert analysis['outcome']['basis'] == 'last_observation'
    assert analysis['outcome']['return_pct'] == -10
    assert analysis['causality'] == 'unverified'
    assert analysis['hypotheses'] and all(h['status'] == 'needs_evidence' for h in analysis['hypotheses'])
    assert report['review_summary']['close_down_count'] == 0
    assert report['review_summary']['close_unknown_count'] == 1


def test_sampled_path_identifies_gain_reversal_without_using_daily_high_or_future(tmp_path):
    from datetime import datetime
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    add_run(repo, 'up', '2026-09-04T10:00:00+08:00', price=11)
    add_run(repo, 'down', '2026-09-04T11:00:00+08:00', price=9)
    add_run(repo, 'future', '2026-09-04T14:00:00+08:00', price=12)
    report = ReviewCenter(repo.db_path).report('limit-up-ambush', '2026-09-04', '2026-09-04', as_of=datetime.fromisoformat('2026-09-04T12:00:00+08:00'))
    event = report['events'][0]
    assert event['post_signal_path']['max_return_pct'] == 10
    assert event['post_signal_path']['min_return_pct'] == -10
    assert event['post_signal_path']['first_below_at'].startswith('2026-09-04T11:00:00')
    assert any(f.get('pattern') == 'sampled_gain_reversed' for f in event['analysis']['facts'])


def test_v1_close_analysis_keeps_next_day_unknown_and_archive_is_immutable(tmp_path):
    from app.review_reports import ReviewReportArchive
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    center, archive = ReviewCenter(repo.db_path), ReviewReportArchive(tmp_path / 'archive.db')
    old = archive.save(center.report('fishing-reversal', '2026-09-04', '2026-09-04'), period='daily')
    ClosingEvidenceStore(tmp_path / 'review_evidence.db').record(evidence(close='9.00'))
    report = center.report('fishing-reversal', '2026-09-04', '2026-09-04')
    event = report['events'][0]
    assert event['analysis']['outcome'] == {'basis':'close', 'return_pct':-10, 'assessment':'below_first'}
    assert '次日结果见独立' in event['analysis']['scope']
    assert report['review_summary']['close_down_count'] == 1
    assert archive.get(old['report_id'])['report']['events'][0]['analysis']['outcome']['basis'] == 'unknown'


def test_conflicting_closes_and_missing_prices_do_not_invent_success_or_causes(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db')
    store.record(evidence(close='9.00'))
    store.record(evidence(close='10.50', source='different-feed'))
    report = ReviewCenter(repo.db_path).report('limit-up-ambush', '2026-09-04', '2026-09-04')
    assert report['events'][0]['analysis']['outcome']['basis'] == 'unknown'
    assert report['events'][0]['analysis']['hypotheses'] == []
    assert report['review_summary']['close_unknown_count'] == 1
