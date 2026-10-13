from datetime import date, datetime, timedelta
from hashlib import sha256

import pytest

from app.repository import StrategyRepository
from app.review_collection import ClosingCollector
from app.review_evidence import ClosingEvidence
from app.review_evidence_store import ClosingEvidenceStore
from test_review_center import add_run


NOW = datetime.fromisoformat('2026-09-04T16:30:00+08:00')


def quote(**changes):
    return ClosingEvidence(**(dict(code='000001', trade_date=date(2026, 9, 4),
                                   close=10, day_high=11, source='boundary-test',
                                   source_reference='test-only-not-product',
                                   price_at=NOW.replace(hour=15, minute=0), fetched_at=NOW) | changes))


class BoundaryProvider:
    source_name = 'boundary-test'

    def __init__(self, result):
        self.result = result

    def fetch(self, code, day):
        return self.result


@pytest.mark.parametrize('changes', [
    {'code': '000002'},
    {'trade_date': date(2026, 9, 3), 'price_at': NOW.replace(day=3, hour=15, minute=0)},
    {'source': 'other-source'},
])
def test_provider_evidence_must_match_claimed_job_and_never_pollute_store(tmp_path, changes):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    original_hash = sha256(repo.db_path.read_bytes()).hexdigest()
    returned = quote(**changes)
    collector = ClosingCollector(repo.db_path, provider=BoundaryProvider(returned), clock=lambda: NOW)
    result = collector.run('2026-09-04', '2026-09-04')
    assert result['failed'] == 1
    assert result['completed'] == 0
    assert collector.jobs()[0]['last_error_type'] == 'EvidenceTargetMismatch'
    assert collector.attempts()[0]['status'] == 'failed'
    store = ClosingEvidenceStore(collector.evidence_path)
    assert store.latest(returned.code, returned.trade_date.isoformat(), as_of=NOW) is None
    assert sha256(repo.db_path.read_bytes()).hexdigest() == original_hash


def test_explicit_recheck_appends_revision_without_changing_default_skip(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    now = NOW
    provider = BoundaryProvider(quote())
    collector = ClosingCollector(repo.db_path, provider=provider, clock=lambda: now)
    assert collector.run('2026-09-04', '2026-09-04')['completed'] == 1
    original = collector.jobs()[0]['evidence_id']
    now += timedelta(minutes=20)
    provider.result = quote(close=10.5, fetched_at=now)
    assert collector.run('2026-09-04', '2026-09-04')['attempted'] == 0
    assert collector.run('2026-09-04', '2026-09-04', recheck_completed=True)['completed'] == 1
    revised = collector.jobs()[0]['evidence_id']
    assert revised != original
    assert [a['evidence_id'] for a in collector.attempts()] == [original, revised]
    store = ClosingEvidenceStore(collector.evidence_path)
    assert store.latest('000001', '2026-09-04', as_of=NOW)['quote']['close'] == '10'
    assert store.latest('000001', '2026-09-04', as_of=now)['quote']['close'] == '10.5'


@pytest.mark.parametrize('returned,error', [(None, 'MissingClosingEvidence'), ({}, 'InvalidClosingEvidence')])
def test_empty_or_untyped_provider_response_is_failed_not_completed(tmp_path, returned, error):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    collector = ClosingCollector(repo.db_path, provider=BoundaryProvider(returned), clock=lambda: NOW)
    result = collector.run('2026-09-04', '2026-09-04')
    assert result['failed'] == 1
    assert result['completed'] == 0
    assert collector.jobs()[0]['last_error_type'] == error
    assert collector.jobs()[0]['evidence_id'] is None
    assert collector.attempts()[0]['status'] == 'failed'


def test_cli_can_explicitly_recheck_completed_evidence(tmp_path, capsys):
    from scripts.collect_review_closes import main
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    args = ['--source-db', str(repo.db_path), '--date-from', '2026-09-04', '--date-to', '2026-09-04']
    provider = BoundaryProvider(quote())
    assert main(args, provider=provider, clock=lambda: NOW) == 0
    later = NOW + timedelta(minutes=20)
    provider.result = quote(close=10.5, fetched_at=later)
    assert main(args + ['--recheck-completed'], provider=provider, clock=lambda: later) == 0
    import json
    outputs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [value['completed'] for value in outputs] == [1, 1]
    assert ClosingEvidenceStore(tmp_path / 'review_evidence.db').latest(
        '000001', '2026-09-04', as_of=later)['quote']['close'] == '10.5'


def test_failed_recheck_keeps_prior_evidence_and_resumes_only_after_cooldown(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    now = NOW
    provider = BoundaryProvider(quote())
    collector = ClosingCollector(repo.db_path, provider=provider, clock=lambda: now)
    collector.run('2026-09-04', '2026-09-04')
    original = collector.jobs()[0]['evidence_id']
    provider.result = None
    assert collector.run('2026-09-04', '2026-09-04', recheck_completed=True)['failed'] == 1
    store = ClosingEvidenceStore(collector.evidence_path)
    assert store.latest('000001', '2026-09-04', as_of=now)['evidence_id'] == original
    now += timedelta(minutes=14)
    provider.result = quote()
    assert collector.run('2026-09-04', '2026-09-04', recheck_completed=True)['attempted'] == 0
    now += timedelta(minutes=1)
    assert collector.run('2026-09-04', '2026-09-04')['completed'] == 1
    assert collector.jobs()[0]['evidence_id'] == original  # identical content is idempotent
    assert [a['status'] for a in collector.attempts()] == ['completed', 'failed', 'completed']


def test_recheck_does_not_steal_active_lease(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    provider = BoundaryProvider(quote())
    collector = ClosingCollector(repo.db_path, provider=provider, clock=lambda: NOW)
    collector.run('2026-09-04', '2026-09-04')
    competing = ClosingCollector(repo.db_path, provider=BoundaryProvider(quote(close=10.5)), clock=lambda: NOW)

    class ReentrantProvider(BoundaryProvider):
        def fetch(self, code, day):
            assert competing.run('2026-09-04', '2026-09-04', recheck_completed=True)['deferred'] == 1
            return self.result

    collector.provider = ReentrantProvider(quote())
    assert collector.run('2026-09-04', '2026-09-04', recheck_completed=True)['completed'] == 1
    assert len(collector.attempts()) == 2


@pytest.mark.parametrize('invalid', ['false', 1, None])
def test_recheck_requires_explicit_boolean_before_writes(tmp_path, invalid):
    collector = ClosingCollector(tmp_path / 'nonexistent-source.db', provider=BoundaryProvider(quote()), clock=lambda: NOW)
    with pytest.raises(ValueError, match='recheck_completed'):
        collector.run('2026-09-04', '2026-09-04', recheck_completed=invalid)
    assert not collector.queue_path.exists()


def test_bounded_rechecks_rotate_to_older_jobs_instead_of_repeating_first_page(tmp_path):
    repo = StrategyRepository(str(tmp_path / 'source.db'))
    add_run(repo, 'first', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal')
    add_run(repo, 'second', '2026-09-04T14:50:00+08:00', strategy_id='fishing-reversal', code='000002')
    now = NOW

    class PerStockProvider(BoundaryProvider):
        def fetch(self, code, day):
            return quote(code=code, fetched_at=now)

    collector = ClosingCollector(repo.db_path, provider=PerStockProvider(None), clock=lambda: now)
    assert collector.run('2026-09-04', '2026-09-04')['completed'] == 2
    now += timedelta(minutes=20)
    for _ in range(2):
        assert collector.run('2026-09-04', '2026-09-04', max_jobs=1, recheck_completed=True)['completed'] == 1
    assert [job['attempt_count'] for job in collector.jobs()] == [2, 2]
