from datetime import date, datetime
import json

import pytest
import requests

from app.review_closing_provider import TencentClosingProvider


NOW = datetime.fromisoformat("2026-09-04T16:30:00+08:00")


class QuoteSession:
    """External HTTP boundary, never used by product code."""
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(self.payload).encode()
        return response


def daily_payload():
    return {"code": 0, "data": {"sz000001": {"day": [
        ["2026-09-03", "11.88", "11.88", "12.08", "11.83", "1105134"],
        ["2026-09-04", "11.86", "11.89", "12.00", "11.85", "814373"],
    ]}}}


def test_fetches_exact_unadjusted_day_and_retains_source_evidence():
    session = QuoteSession(daily_payload())
    quote = TencentClosingProvider(session=session, clock=lambda: NOW).fetch("000001", date(2026, 9, 4))
    assert str(quote.close) == "11.89"
    assert str(quote.day_high) == "12.00"
    assert quote.limit_up is None
    assert quote.limit_touch_times == ()
    assert quote.price_basis == "unadjusted"
    assert quote.price_time_basis == "daily_session_end"
    assert quote.source_payload["symbol"] == "sz000001"
    assert quote.source_payload["day"][0] == "2026-09-04"
    assert quote.fetch_started_at == NOW
    assert quote.fetched_at == NOW
    assert "sha256=" in quote.source_reference
    assert session.calls[0][1]["params"]["param"] == "sz000001,day,2026-09-04,2026-09-04,2,"
    assert session.calls[0][1]["timeout"] == (5, 15)


@pytest.mark.parametrize("code, now", [
    ("000001", "2026-09-04T14:59:00+08:00"),
    ("000001", "2026-09-04T15:59:59+08:00"),
    ("000001", "2026-09-03T17:00:00+08:00"),
    ("000001", "2026-09-04T16:30:00"),
    ("920001", "2026-09-04T16:30:00+08:00"),
    ("399001", "2026-09-04T16:30:00+08:00"),
    ("000001,evil", "2026-09-04T16:30:00+08:00"),
])
def test_not_ready_or_unsupported_requests_never_fetch(code, now):
    session = QuoteSession(daily_payload())
    with pytest.raises(ValueError):
        TencentClosingProvider(session=session, clock=lambda: datetime.fromisoformat(now)).fetch(code, date(2026, 9, 4))
    assert session.calls == []


@pytest.mark.parametrize("case", ["wrong_day", "adjusted_only", "wrong_symbol", "duplicate", "error", "zero_volume", "bad_ohlc"])
def test_invalid_vendor_bar_remains_unavailable(case):
    payload = daily_payload()
    target = payload["data"]["sz000001"]
    if case == "wrong_day":
        target["day"] = target["day"][:1]
    elif case == "adjusted_only":
        target["qfqday"] = target.pop("day")
    elif case == "wrong_symbol":
        payload["data"]["sz000002"] = payload["data"].pop("sz000001")
    elif case == "duplicate":
        target["day"].append(target["day"][-1].copy())
    elif case == "error":
        payload["code"] = -1
    elif case == "zero_volume":
        target["day"][-1][5] = "0"
    elif case == "bad_ohlc":
        target["day"][-1][4] = "12.50"
    with pytest.raises(ValueError):
        TencentClosingProvider(session=QuoteSession(payload), clock=lambda: NOW).fetch("000001", date(2026, 9, 4))


def test_collects_shared_security_once_and_keeps_source_readonly(tmp_path):
    from hashlib import sha256
    from app.repository import StrategyRepository
    from app.review_center import ReviewCenter
    from app.review_collection import ClosingCollector
    from test_review_center import add_run

    source = tmp_path / "source.db"
    repo = StrategyRepository(str(source))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    add_run(repo, "v1", "2026-09-04T14:50:00+08:00", strategy_id="fishing-reversal")
    source_hash = sha256(source.read_bytes()).hexdigest()
    session = QuoteSession(daily_payload())
    collector = ClosingCollector(source, provider=TencentClosingProvider(session=session, clock=lambda: NOW), clock=lambda: NOW)
    result = collector.run("2026-09-04", "2026-09-04")
    assert result["completed"] == 1
    assert result["failed"] == 0
    assert len(session.calls) == 1
    repeated = collector.run("2026-09-04", "2026-09-04")
    assert repeated["attempted"] == 0
    assert len(session.calls) == 1
    assert sha256(source.read_bytes()).hexdigest() == source_hash
    assert collector.jobs()[0]["status"] == "completed"
    assert collector.jobs()[0]["attempt_count"] == 1
    report = ReviewCenter(source).report("limit-up-ambush", "2026-09-04", "2026-09-04", as_of=NOW)
    assert report["metrics"]["close_positive_rate"]["rate_pct"] == 100
    assert report["metrics"]["close_limit_rate"]["rate_pct"] is None


def test_interrupted_job_recovers_after_lease_expiry(tmp_path):
    from datetime import timedelta
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    now = NOW

    class InterruptedSession(QuoteSession):
        def get(self, url, **kwargs):
            raise SystemExit("simulate process termination")

    first = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=InterruptedSession(daily_payload()), clock=lambda: now), clock=lambda: now)
    with pytest.raises(SystemExit):
        first.run("2026-09-04", "2026-09-04")
    assert first.jobs()[0]["status"] == "running"
    resumed = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=QuoteSession(daily_payload()), clock=lambda: now), clock=lambda: now)
    assert resumed.run("2026-09-04", "2026-09-04")["attempted"] == 0
    now += timedelta(minutes=10)
    assert resumed.run("2026-09-04", "2026-09-04")["completed"] == 1
    assert [item["status"] for item in resumed.attempts()] == ["abandoned", "completed"]


def test_expired_worker_cannot_overwrite_newer_collection(tmp_path):
    from datetime import timedelta
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from app.review_center import ReviewCenter
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    now = NOW
    fresh_payload = daily_payload()
    fresh_payload["data"]["sz000001"]["day"][-1][2] = "11.99"
    replacement = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=QuoteSession(fresh_payload), clock=lambda: now), clock=lambda: now)

    class SlowSession(QuoteSession):
        def get(self, url, **kwargs):
            nonlocal now
            now += timedelta(minutes=11)
            assert replacement.run("2026-09-04", "2026-09-04")["completed"] == 1
            return super().get(url, **kwargs)

    slow = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=SlowSession(daily_payload()), clock=lambda: now), clock=lambda: now)
    assert slow.run("2026-09-04", "2026-09-04")["lease_lost"] == 1
    quote = ReviewCenter(repo.db_path).report("limit-up-ambush", "2026-09-04", "2026-09-04", as_of=now)["events"][0]["closing_evidence"]["quote"]
    assert quote["close"] == "11.99"


def test_failed_collection_is_recorded_and_retries_after_cooldown(tmp_path):
    from datetime import timedelta
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from test_review_center import add_run

    class FlakySession(QuoteSession):
        def get(self, url, **kwargs):
            response = super().get(url, **kwargs)
            if len(self.calls) == 1:
                raise requests.Timeout("do-not-persist-sensitive-transport-details")
            return response

    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    now = NOW
    session = FlakySession(daily_payload())
    provider = TencentClosingProvider(session=session, clock=lambda: now)
    collector = ClosingCollector(repo.db_path, provider=provider, clock=lambda: now)
    assert collector.run("2026-09-04", "2026-09-04")["failed"] == 1
    job = collector.jobs()[0]
    assert job["status"] == "failed"
    assert job["last_error_type"] == "Timeout"
    assert "sensitive" not in json.dumps(job)
    now += timedelta(minutes=14)
    assert collector.run("2026-09-04", "2026-09-04")["attempted"] == 0
    now += timedelta(minutes=1)
    # A new instance must resume the persisted job.
    resumed = ClosingCollector(repo.db_path, provider=provider, clock=lambda: now)
    assert resumed.run("2026-09-04", "2026-09-04")["completed"] == 1
    assert resumed.jobs()[0]["attempt_count"] == 2
    attempts = resumed.attempts()
    assert [item["status"] for item in attempts] == ["failed", "completed"]


@pytest.mark.parametrize("collision", ["source_evidence", "source_queue", "queue_evidence", "hardlink"])
def test_collection_databases_must_be_separate_before_any_writes(tmp_path, collision):
    from app.review_collection import ClosingCollector
    source, evidence_db, queue = (tmp_path / name for name in ("source.db", "evidence.db", "queue.db"))
    source.write_bytes(b"preserved-source")
    if collision == "source_evidence":
        evidence_db = source
    elif collision == "source_queue":
        queue = source
    elif collision == "queue_evidence":
        queue = evidence_db
    else:
        evidence_db.hardlink_to(source)
    with pytest.raises(ValueError, match="separate"):
        ClosingCollector(source, evidence_db=evidence_db, queue_db=queue)
    assert source.read_bytes() == b"preserved-source"


def test_unclosed_jobs_stay_pending_and_batch_limit_resumes(tmp_path):
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    add_run(repo, "second", "2026-09-04T10:00:00+08:00", code="000002")
    payload = daily_payload()
    payload["data"]["sz000002"] = payload["data"]["sz000001"]
    session = QuoteSession(payload)
    now = NOW.replace(hour=14)
    collector = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=session, clock=lambda: now), clock=lambda: now)
    early = collector.run("2026-09-04", "2026-09-04", max_jobs=1)
    assert early["attempted"] == 0
    assert early["deferred"] == 2
    assert {row["status"] for row in collector.jobs()} == {"pending"}
    assert session.calls == []
    now = NOW
    assert collector.run("2026-09-04", "2026-09-04", max_jobs=1)["completed"] == 1
    assert collector.run("2026-09-04", "2026-09-04", max_jobs=1)["completed"] == 1
    assert collector.run("2026-09-04", "2026-09-04", max_jobs=1)["attempted"] == 0
    for limit in (0, -1, 501, True):
        with pytest.raises(ValueError):
            collector.run("2026-09-04", "2026-09-04", max_jobs=limit)


def test_overlapping_collectors_do_not_fetch_same_job_twice(tmp_path):
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    other_session = QuoteSession(daily_payload())
    other = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=other_session, clock=lambda: NOW), clock=lambda: NOW)
    overlapping = []

    class ConcurrentSession(QuoteSession):
        def get(self, url, **kwargs):
            overlapping.append(other.run("2026-09-04", "2026-09-04"))
            return super().get(url, **kwargs)

    collector = ClosingCollector(repo.db_path, provider=TencentClosingProvider(session=ConcurrentSession(daily_payload()), clock=lambda: NOW), clock=lambda: NOW)
    assert collector.run("2026-09-04", "2026-09-04")["completed"] == 1
    assert overlapping[0]["attempted"] == 0
    assert other_session.calls == []
    assert collector.jobs()[0]["attempt_count"] == 1


def test_collection_cli_reports_completion_and_skips_completed_jobs(tmp_path, capsys):
    from app.repository import StrategyRepository
    from scripts.collect_review_closes import main
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    arguments = ["--source-db", str(repo.db_path), "--date-from", "2026-09-04", "--date-to", "2026-09-04"]
    provider = TencentClosingProvider(session=QuoteSession(daily_payload()), clock=lambda: NOW)
    assert main(arguments, provider=provider, clock=lambda: NOW) == 0
    assert json.loads(capsys.readouterr().out)["completed"] == 1
    assert main(arguments, provider=provider, clock=lambda: NOW) == 0
    assert json.loads(capsys.readouterr().out)["attempted"] == 0


def test_collection_cli_keeps_success_when_another_stock_fails(tmp_path, capsys):
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from scripts.collect_review_closes import main
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "missing", "2026-09-04T09:40:00+08:00", code="000000")
    add_run(repo, "good", "2026-09-04T09:42:00+08:00")
    provider = TencentClosingProvider(session=QuoteSession(daily_payload()), clock=lambda: NOW)
    result = main(["--source-db", str(repo.db_path), "--date-from", "2026-09-04", "--date-to", "2026-09-04"],
                  provider=provider, clock=lambda: NOW)
    assert result == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["failed"] == summary["completed"] == 1
    assert [job["status"] for job in ClosingCollector(repo.db_path).jobs()] == ["failed", "completed"]


def test_rejected_stale_evidence_is_recorded_as_failed_not_stuck_running(tmp_path):
    from app.repository import StrategyRepository
    from app.review_collection import ClosingCollector
    from app.review_evidence_store import ClosingEvidenceStore
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "alert", "2026-09-04T09:40:00+08:00")
    provider = TencentClosingProvider(session=QuoteSession(daily_payload()), clock=lambda: NOW)
    quote = provider.fetch("000001", date(2026, 9, 4))
    newest = type(quote).model_validate({**quote.model_dump(), "fetched_at": NOW.replace(hour=17), "close": "11.99"})
    clock = lambda: NOW.replace(hour=18)
    store = ClosingEvidenceStore(tmp_path / "review_evidence.db", clock=clock)
    evidence_id = store.record(newest)
    collector = ClosingCollector(repo.db_path, provider=provider, clock=clock)
    assert collector.run("2026-09-04", "2026-09-04")["failed"] == 1
    assert collector.jobs()[0]["status"] == "failed"
    assert store.latest("000001", "2026-09-04", as_of=clock())["evidence_id"] == evidence_id
