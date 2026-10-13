from datetime import datetime, timedelta
from hashlib import sha256

import pytest

from app.repository import StrategyRepository
from app.review_collection import ClosingCollector
from test_review_center import add_run
from test_review_collection_contract import BoundaryProvider, quote


NOW = datetime.fromisoformat('2026-09-04T16:30:00+08:00')


def test_queue_pages_match_filters_without_fetching_or_mutating_data(tmp_path):
    from app.review_collection_status import ClosingQueueReader

    repo = StrategyRepository(str(tmp_path / 'source.db'))
    for code in ['000003', '000001', '000002']:
        add_run(repo, code, '2026-09-04T09:40:00+08:00', code=code)
    collector = ClosingCollector(repo.db_path, provider=BoundaryProvider(quote()), clock=lambda: NOW)
    assert collector.run('2026-09-04', '2026-09-04', max_jobs=1)['completed'] == 1
    paths = [repo.db_path, collector.queue_path, collector.evidence_path]
    before = [sha256(path.read_bytes()).hexdigest() for path in paths]

    reader = ClosingQueueReader(collector.queue_path, clock=lambda: NOW)
    first = reader.search(status='pending', limit=1)
    assert first['total'] == 2
    assert first['counts_by_status'] == {'pending': 2}
    assert [item['code'] for item in first['items']] == ['000002']
    assert first['items'][0]['availability'] == 'ready'
    assert first['next_offset'] == 1
    second = reader.search(status='pending', limit=1, offset=first['next_offset'])
    assert [item['code'] for item in second['items']] == ['000003']
    assert second['next_offset'] is None
    assert reader.search(code='000001')['items'][0]['availability'] == 'completed'
    assert reader.search(date_from='2026-09-03', date_to='2026-09-03')['total'] == 0
    assert 'lease_token' not in str(first)
    assert [sha256(path.read_bytes()).hexdigest() for path in paths] == before


@pytest.mark.parametrize('state, expected, delay', [
    ('pending', 'awaiting_close', timedelta(hours=2)),
    ('failed', 'cooldown', timedelta(minutes=15)),
    ('running', 'running', timedelta(minutes=10)),
])
def test_queue_distinguishes_waiting_cooldown_and_expired_lease(tmp_path, state, expected, delay):
    import requests
    from app.review_collection_status import ClosingQueueReader

    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    now = NOW.replace(hour=14, minute=0) if state == 'pending' else NOW

    class UnavailableProvider(BoundaryProvider):
        def fetch(self, code, day):
            if state == 'running':
                raise SystemExit('interrupted-test-only')
            raise requests.Timeout('never-expose-this-private-transport-detail')

    collector = ClosingCollector(repo.db_path, provider=UnavailableProvider(None), clock=lambda: now)
    if state == 'running':
        with pytest.raises(SystemExit):
            collector.run('2026-09-04', '2026-09-04')
    else:
        collector.run('2026-09-04', '2026-09-04')
    reader = ClosingQueueReader(collector.queue_path, clock=lambda: now)
    before = sha256(collector.queue_path.read_bytes()).hexdigest()
    item = reader.search()['items'][0]
    assert item['availability'] == expected
    assert item['ready_to_collect'] is False
    assert item['next_eligible_at'] == (now + delay).isoformat()
    if state == 'failed':
        assert item['last_error_type'] == 'Timeout'
    now += delay
    ready = reader.search()['items'][0]
    assert ready['availability'] == ('lease_expired' if state == 'running' else 'ready')
    assert ready['ready_to_collect'] is True
    assert sha256(collector.queue_path.read_bytes()).hexdigest() == before
    assert 'private-transport' not in str(item)


@pytest.mark.parametrize('changes', [
    {'status': 'running', 'lease_until': None},
    {'status': 'running', 'lease_until': '2026-09-04T16:40:00'},
    {'status': 'failed', 'next_retry_at': 'invalid-time'},
    {'status': 'legacy-unknown'},
])
def test_unverifiable_legacy_queue_state_is_unknown_not_ready(tmp_path, changes):
    import sqlite3
    from app.review_collection_status import ClosingQueueReader

    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    collector = ClosingCollector(repo.db_path, provider=BoundaryProvider(None), clock=lambda: NOW)
    collector.run('2026-09-04', '2026-09-04')
    # Storage boundary: simulate a malformed legacy record, not product data.
    with sqlite3.connect(collector.queue_path) as connection:
        connection.execute('UPDATE closing_jobs SET '+','.join(key+'=?' for key in changes), tuple(changes.values()))
    before = sha256(collector.queue_path.read_bytes()).hexdigest()
    result = ClosingQueueReader(collector.queue_path, clock=lambda: NOW).search()
    assert result['items'][0]['availability'] == 'unknown'
    assert result['items'][0]['ready_to_collect'] is False
    assert result['items'][0]['next_eligible_at'] is None
    assert result['items'][0]['diagnostic_flags']
    assert sha256(collector.queue_path.read_bytes()).hexdigest() == before


def test_queue_api_is_readonly_and_reports_uninitialized_queue(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.chdir(tmp_path)
    from app import main

    repo = StrategyRepository(str(tmp_path / 'source.db'))
    monkeypatch.setattr(main, 'repository', repo)
    client = TestClient(main.app)
    source_hash = sha256(repo.db_path.read_bytes()).hexdigest()
    response = client.get('/api/review/collection/jobs')
    assert response.status_code == 200
    assert response.json()['queue_status'] == 'not_initialized'
    assert response.json()['items'] == []
    assert response.json()['total'] == 0
    assert not (tmp_path / 'review_collection.db').exists()
    assert not (tmp_path / 'review_evidence.db').exists()
    assert sha256(repo.db_path.read_bytes()).hexdigest() == source_hash
    assert client.post('/api/review/collection/jobs').status_code == 405


@pytest.mark.parametrize('params', [
    {'limit': True}, {'limit': 0}, {'limit': 201}, {'offset': -1}, {'offset': 1000001},
    {'date_from': '2026-09-04'}, {'date_to': '2026-09-04'},
    {'date_from': '2026-09-05', 'date_to': '2026-09-04'},
    {'date_from': '2025-01-01', 'date_to': '2026-09-04'},
    {'date_from': '1899-01-01', 'date_to': '1899-01-02'},
    {'code': "000001' OR 1=1 --"}, {'code': '１２３４５６'}, {'status': 'anything'},
])
def test_invalid_queue_queries_are_rejected_even_before_a_queue_exists(tmp_path, params):
    from app.review_collection_status import ClosingQueueReader
    path = tmp_path / 'absent' / 'queue.db'
    with pytest.raises(ValueError):
        ClosingQueueReader(path, clock=lambda: NOW).search(**params)
    assert not path.parent.exists()


def test_attempt_history_keeps_failed_then_recovered_evidence_with_exact_job_scope(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.chdir(tmp_path)
    from app import main

    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T09:40:00+08:00')
    now = NOW
    provider = BoundaryProvider(None)
    collector = ClosingCollector(repo.db_path, provider=provider, clock=lambda: now)
    assert collector.run('2026-09-04', '2026-09-04')['failed'] == 1
    now += timedelta(minutes=20)
    provider.result = quote(fetched_at=now)
    assert collector.run('2026-09-04', '2026-09-04')['completed'] == 1
    before = sha256(collector.queue_path.read_bytes()).hexdigest()
    monkeypatch.setattr(main, 'repository', repo)
    client = TestClient(main.app)
    query = {'trade_date': '2026-09-04', 'code': '000001', 'provider': 'boundary-test', 'limit': 1}
    page = client.get('/api/review/collection/attempts', params=query)
    assert page.status_code == 200
    result = page.json()
    assert result['total'] == 2
    assert result['job']['status'] == 'completed'
    assert result['items'][0]['status'] == 'completed'
    assert result['items'][0]['evidence_id'] == result['job']['evidence_id']
    prior = client.get('/api/review/collection/attempts', params=query | {'offset': result['next_offset']}).json()
    assert prior['items'][0]['status'] == 'failed'
    assert prior['items'][0]['error_type'] == 'MissingClosingEvidence'
    assert prior['next_offset'] is None
    other = client.get('/api/review/collection/attempts', params=query | {'provider': 'other-source'}).json()
    assert other['total'] == 0 and other['job'] is None
    assert 'attempt_id' not in str(result) and 'lease_token' not in str(result)
    assert sha256(collector.queue_path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize('route, params', [
    ('jobs', {'date_from': '2026-09-04'}),
    ('jobs', {'date_from': '2026-09-05', 'date_to': '2026-09-04'}),
    ('jobs', {'limit': 201}), ('jobs', {'code': "000001' OR 1=1 --"}),
    ('attempts', {}),
    ('attempts', {'trade_date': '2026-09-04', 'code': '000001', 'provider': '   '}),
])
def test_queue_api_validates_inputs_without_creating_storage(tmp_path, monkeypatch, route, params):
    from fastapi.testclient import TestClient
    monkeypatch.chdir(tmp_path)
    from app import main
    monkeypatch.setattr(main, 'repository', StrategyRepository(str(tmp_path / 'source.db')))
    assert TestClient(main.app).get('/api/review/collection/' + route, params=params).status_code == 422
    assert not (tmp_path / 'review_collection.db').exists()


@pytest.mark.parametrize('route, params', [
    ('jobs', {}), ('attempts', {'trade_date': '2026-09-04', 'code': '000001', 'provider': 'boundary-test'}),
])
def test_unreadable_queue_returns_safe_503_not_empty_success(tmp_path, monkeypatch, route, params):
    from fastapi.testclient import TestClient
    monkeypatch.chdir(tmp_path)
    from app import main
    monkeypatch.setattr(main, 'repository', StrategyRepository(str(tmp_path / 'source.db')))
    path = tmp_path / 'review_collection.db'
    path.write_bytes(b'not-a-sqlite-database-private-content')
    response = TestClient(main.app).get('/api/review/collection/' + route, params=params)
    assert response.status_code == 503
    assert 'private-content' not in response.text and str(tmp_path) not in response.text
    assert path.read_bytes() == b'not-a-sqlite-database-private-content'


def test_readonly_status_uses_timezone_aware_clock(tmp_path):
    from datetime import timezone
    from app.review_collection_status import ClosingQueueReader
    path = tmp_path / 'missing.db'
    utc = ClosingQueueReader(path, clock=lambda: NOW.astimezone(timezone.utc)).search()
    local = ClosingQueueReader(path, clock=lambda: NOW).search()
    assert utc == local
    with pytest.raises(ValueError):
        ClosingQueueReader(path, clock=lambda: NOW.replace(tzinfo=None)).search()
    assert not path.exists()
