from datetime import datetime, date
from hashlib import sha256
import pytest

from app.repository import StrategyRepository
from app.review_center import ReviewCenter
from app.review_evidence import ClosingEvidence
from app.review_evidence_store import ClosingEvidenceStore
from test_review_center import add_run


NOW = datetime.fromisoformat('2026-09-07T16:30:00+08:00')


def setup_event(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    return repo


def close_quote(day='2026-09-07', **changes):
    return ClosingEvidence(**(dict(code='000001', trade_date=date.fromisoformat(day),
        close=10.5, day_high=11, source='test-only', source_reference='test-only',
        price_at=datetime.fromisoformat(day + 'T15:00:00+08:00'), fetched_at=NOW) | changes))


def report(repo, as_of=NOW):
    return ReviewCenter(repo.db_path).report('fishing-reversal', '2026-09-04', '2026-09-04', as_of=as_of)


def test_v1_next_scheduled_session_close_is_separate_from_signal_day_and_rule_exit(tmp_path):
    repo = setup_event(tmp_path)
    digest = sha256(repo.db_path.read_bytes()).hexdigest()
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    evidence_id = store.record(close_quote())
    result = report(repo)
    event = result['events'][0]
    outcome = event['next_day_close']
    assert outcome['calendar']['next_date'] == '2026-09-07'
    assert outcome['status'] == 'close_available'
    assert outcome['close_return_pct'] == 5
    assert outcome['closing_evidence']['evidence_id'] == evidence_id
    assert event['t1_review']['status'] == 'missing'  # no simulation required for a market outcome
    assert event['close_return_pct'] is None
    assert result['metrics']['close_positive_rate']['eligible_count'] == 0
    assert result['next_day_metrics']['close_positive_rate']['rate_pct'] == 100
    assert sha256(repo.db_path.read_bytes()).hexdigest() == digest


def test_collection_fills_next_day_close_without_a_legacy_rule_result(tmp_path):
    from app.review_collection import ClosingCollector
    repo = setup_event(tmp_path)
    calls = []

    class Provider:
        source_name = 'test-only'

        def fetch(self, code, day):
            calls.append((code, day.isoformat()))
            return close_quote(day.isoformat(), code=code)

    collector = ClosingCollector(repo.db_path, provider=Provider(), clock=lambda: NOW)
    result = collector.run('2026-09-04', '2026-09-04')
    assert result['completed'] == 2
    assert calls == [('000001', '2026-09-04'), ('000001', '2026-09-07')]
    assert report(repo)['events'][0]['next_day_close']['status'] == 'close_available'
    assert collector.run('2026-09-04', '2026-09-04')['attempted'] == 0


@pytest.mark.parametrize('as_of,status', [
    ('2026-09-07T14:59:00+08:00','not_yet_closed'),
    ('2026-09-07T15:00:00+08:00','pending_close'),
    ('2026-09-07T08:29:59+00:00','pending_close'),
    ('2026-09-07T08:30:00+00:00','close_available'),
])
def test_next_day_close_respects_actual_evidence_receipt_and_asof(tmp_path, as_of, status):
    repo = setup_event(tmp_path)
    ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW).record(close_quote())
    result = report(repo, datetime.fromisoformat(as_of))
    assert result['events'][0]['next_day_close']['status'] == status
    assert result['next_day_metrics']['close_positive_rate']['eligible_count'] == (status == 'close_available')


def test_wrong_day_quotes_and_multi_source_conflict_do_not_become_next_day_success(tmp_path):
    repo = setup_event(tmp_path)
    store = ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW)
    store.record(close_quote('2026-09-04'))
    assert report(repo)['events'][0]['next_day_close']['status'] == 'pending_close'
    store.record(close_quote())
    store.record(close_quote(source='second-test-source', close=9.5))
    result = report(repo)
    assert result['events'][0]['next_day_close']['status'] == 'closing_source_conflict'
    assert result['next_day_metrics']['close_positive_rate']['unknown_count'] == 1


def test_late_next_day_close_creates_new_report_revision_without_rewriting_old(tmp_path):
    from app.review_reports import ReviewReportArchive
    repo = setup_event(tmp_path)
    archive = ReviewReportArchive(tmp_path / 'reports.db')
    first = archive.save(report(repo), period='daily')
    ClosingEvidenceStore(tmp_path / 'review_evidence.db', clock=lambda: NOW).record(close_quote())
    second = archive.save(report(repo), period='daily')
    assert second['revision'] == first['revision'] + 1
    assert archive.get(first['report_id'])['report']['events'][0]['next_day_close']['status'] == 'pending_close'
    assert archive.get(second['report_id'])['report']['events'][0]['next_day_close']['close_return_pct'] == 5


def test_default_worker_revises_preholiday_v1_reports_when_next_session_arrives(tmp_path):
    from app.review_scheduler import ReviewReportScheduler
    from app.review_reports import ReviewReportArchive
    from datetime import timedelta
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'before-holiday', '2026-02-13T14:50:00+08:00', strategy_id='fishing-reversal')
    center = ReviewCenter(repo.db_path)
    archive = ReviewReportArchive(tmp_path / 'review_reports.db')
    first = archive.save(center.report('fishing-reversal', '2026-02-13', '2026-02-13',
        as_of=datetime.fromisoformat('2026-02-13T18:00:00+08:00')), period='daily')
    before = sha256(repo.db_path.read_bytes()).hexdigest()
    clock = [datetime.fromisoformat('2026-02-24T16:30:00+08:00')]
    calls = []

    class Provider:
        source_name = 'test-only'

        def fetch(self, code, day):
            calls.append((code, day.isoformat()))
            return close_quote(day.isoformat(), code=code, fetched_at=clock[0])

    worker = ReviewReportScheduler(repo.db_path, provider=Provider(), clock=lambda: clock[0])
    result = worker.tick()  # seven calendar days must not lose the Feb 13 recommendation
    assert result['status'] == 'completed'
    assert ('000001', '2026-02-24') in calls
    old = archive.get(first['report_id'])['report']['events'][0]
    assert old['next_day_close']['status'] == 'not_yet_closed'
    latest = archive.search(strategy_id='fishing-reversal', period='daily',
        date_from='2026-02-13', date_to='2026-02-13', latest_only=True)['reports'][0]
    assert latest['revision'] == first['revision'] + 1
    assert archive.get(latest['report_id'])['report']['next_day_metrics']['close_positive_rate']['rate_pct'] == 100
    weekly = archive.search(strategy_id='fishing-reversal', period='weekly',
        date_from='2026-02-13', date_to='2026-02-13', latest_only=True)['reports'][0]
    assert archive.get(weekly['report_id'])['report']['events'][0]['next_day_close']['status'] == 'close_available'
    assert archive.search(strategy_id='limit-up-ambush', date_from='2026-02-13', date_to='2026-02-13')['total'] == 0
    total = archive.search()['total']
    clock[0] += timedelta(minutes=15)
    assert worker.tick()['status'] == 'completed'
    assert archive.search()['total'] == total
    assert calls.count(('000001', '2026-02-24')) == 1
    assert sha256(repo.db_path.read_bytes()).hexdigest() == before
