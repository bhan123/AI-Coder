from datetime import datetime


def test_due_reports_follow_shanghai_deadlines_and_catch_up_after_restart():
    from app.review_scheduler import due_windows
    assert due_windows(datetime.fromisoformat('2026-09-04T08:29:00+00:00'), lookback_days=1) == []
    daily = due_windows(datetime.fromisoformat('2026-09-04T08:30:00+00:00'), lookback_days=1)
    assert daily == [('daily','2026-09-04','2026-09-04')]
    assert due_windows(datetime.fromisoformat('2026-09-04T18:00:00+08:00'), lookback_days=1)[-1] == ('weekly','2026-08-31','2026-09-04')
    saturday = due_windows(datetime.fromisoformat('2026-09-05T09:00:00+08:00'), lookback_days=2)
    assert saturday == [('daily','2026-09-04','2026-09-04'), ('weekly','2026-08-31','2026-09-04')]


def test_worker_collects_archives_both_strategies_and_repeats_without_new_revisions(tmp_path):
    from app.review_scheduler import ReviewReportScheduler
    from app.review_reports import ReviewReportArchive
    from app.repository import StrategyRepository
    from test_review_center import add_run
    from test_review_evidence import evidence
    from hashlib import sha256
    class Feed:
        source_name = 'test-feed'
        def fetch(self, code, day):
            return evidence(close='9.00')
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    before = sha256(repo.db_path.read_bytes()).hexdigest()
    clock = [datetime.fromisoformat('2026-09-04T18:00:00+08:00')]
    worker = ReviewReportScheduler(repo.db_path, provider=Feed(), clock=lambda:clock[0])
    result = worker.tick(lookback_days=1)
    assert result['status'] == 'completed'
    assert len(result['reports']) == 4
    archive = ReviewReportArchive(tmp_path / 'review_reports.db')
    alert = archive.search(strategy_id='limit-up-ambush',period='daily')['reports'][0]
    assert archive.get(alert['report_id'])['report']['review_summary']['close_down_count'] == 1
    assert worker.tick(lookback_days=1)['status'] == 'cooldown'
    clock[0] += __import__('datetime').timedelta(minutes=15)
    assert worker.tick(lookback_days=1)['status'] == 'completed'
    assert archive.search()['total'] == 4
    assert sha256(repo.db_path.read_bytes()).hexdigest() == before
    assert worker.status()['last_run']['status'] == 'completed'


def test_collection_failure_still_archives_unknown_results_and_status_is_read_only(tmp_path, monkeypatch):
    from app.review_scheduler import ReviewReportScheduler
    from app.review_reports import ReviewReportArchive
    from app.repository import StrategyRepository
    from test_review_center import add_run
    from app import main
    from fastapi.testclient import TestClient
    class Feed:
        source_name = 'test-feed'
        def fetch(self, code, day):
            raise ValueError('secret-token-must-not-leak')
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    monkeypatch.setattr(main, 'repository', repo)
    client = TestClient(main.app)
    response = client.get('/api/review/automation')
    assert response.status_code == 200
    assert response.json()['last_run'] is None
    assert not (tmp_path / 'review_scheduler.db').exists()
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    worker = ReviewReportScheduler(repo.db_path, provider=Feed(), clock=lambda:datetime.fromisoformat('2026-09-04T16:30:00+08:00'))
    result = worker.tick(lookback_days=1)
    assert result['status'] == 'partial'
    assert len(result['reports']) == 2
    assert result['collection']['failed'] == 1
    assert 'secret-token' not in str(worker.status())
    assert client.get('/api/review/automation').json()['last_run']['status'] == 'partial'
    assert client.post('/api/review/automation').status_code == 405
    archive = ReviewReportArchive(tmp_path / 'review_reports.db')
    record = archive.search(strategy_id='limit-up-ambush')['reports'][0]
    assert archive.get(record['report_id'])['report']['review_summary']['close_unknown_count'] == 1


def test_overlapping_worker_is_blocked_and_expired_worker_cannot_archive(tmp_path):
    from app.review_scheduler import ReviewReportScheduler
    from app.repository import StrategyRepository
    from test_review_center import add_run
    from test_review_evidence import evidence
    from datetime import timedelta
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    clock = [datetime.fromisoformat('2026-09-04T16:30:00+08:00')]
    class Feed:
        source_name = 'test-feed'
        def fetch(self, code, day):
            assert other.tick(lookback_days=1)['status'] == 'running'
            clock[0] += timedelta(minutes=16)
            assert other.status()['last_run']['status'] == 'lease_expired'
            return evidence()
    worker = ReviewReportScheduler(repo.db_path, provider=Feed(), clock=lambda:clock[0])
    other = ReviewReportScheduler(repo.db_path, provider=Feed(), clock=lambda:clock[0])
    assert worker.tick(lookback_days=1)['status'] == 'lease_lost'
    assert not (tmp_path / 'review_reports.db').exists()


def test_invalid_paths_and_clock_are_rejected_before_writing(tmp_path):
    import pytest
    from app.review_scheduler import ReviewReportScheduler, due_windows
    with pytest.raises(ValueError, match='separate'):
        ReviewReportScheduler(tmp_path / 'review_reports.db')
    with pytest.raises(ValueError):
        due_windows(datetime(2026,9,4,18))
    with pytest.raises(ValueError):
        due_windows(datetime.fromisoformat('2026-09-04T18:00:00+08:00'), lookback_days=366)
    assert list(tmp_path.iterdir()) == []


def test_cli_plan_does_not_touch_data_or_contact_provider(tmp_path, capsys):
    from scripts.run_review_reports import main
    import json
    assert main(['--source-db', str(tmp_path/'absent.db'), '--plan', '--lookback-days', '1'],
                clock=lambda:datetime.fromisoformat('2026-09-04T18:00:00+08:00')) == 0
    assert json.loads(capsys.readouterr().out)['windows'][-1][0] == 'weekly'
    assert list(tmp_path.iterdir()) == []
