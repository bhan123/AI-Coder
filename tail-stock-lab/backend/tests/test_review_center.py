from datetime import datetime

import pytest

from app.models import MarketSnapshot, Signal, StrategyRun
from app.repository import StrategyRepository
from app.review_center import ReviewCenter


def add_run(repo, run_id, at, *, price=10.0, strategy_id="limit-up-ambush",
            code="000001", version="0.2.0", mode="live", origin="scheduled",
            signals=True):
    observed = datetime.fromisoformat(at)
    snapshot = MarketSnapshot(code=code, name="测试股票", price=price,
                              pct_change=5, day_low=9, captured_at=observed)
    run = StrategyRun(
        run_id=run_id, strategy_id=strategy_id, version=version,
        observed_at=observed, mode=mode, capture_origin=origin,
        execution_status="tradable", data_source="test", universe_size=100,
        signals=[Signal(code=code, name="测试股票", score=80, eligible=True,
                        reason="测试信号", risk_level="low", factors=[],
                        snapshot=snapshot)] if signals else [],
    )
    repo.save_run(run)
    if strategy_id == "limit-up-ambush":
        repo.record_alert_run(run)
    return run


def test_ledger_deduplicates_daily_alerts_without_claiming_a_close(tmp_path):
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    add_run(repo, "repeat", "2026-09-04T14:58:00+08:00", price=9)

    report = ReviewCenter(repo.db_path).report("limit-up-ambush", "2026-09-04", "2026-09-04")

    assert report["event_count"] == 1
    event = report["events"][0]
    assert event["first_run_id"] == "first"
    assert event["first_price"] == 10
    assert event["last_observed_return_pct"] == pytest.approx(-10)
    assert report["metrics"]["close_positive_rate"] == {
        "success_count": 0, "eligible_count": 0, "unknown_count": 1,
        "rate_pct": None, "coverage_pct": 0.0,
    }
    assert "close_unverified" in event["quality_flags"]


def test_report_keeps_zero_signal_days_and_excludes_nonformal_and_future_data(tmp_path):
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "zero", "2026-09-03T14:50:00+08:00", signals=False)
    add_run(repo, "first", "2026-09-04T01:40:00+00:00")
    add_run(repo, "new-version", "2026-09-04T10:00:00+08:00", version="0.3.0")
    add_run(repo, "manual", "2026-09-04T10:01:00+08:00", code="000002", origin="manual")
    add_run(repo, "sample", "2026-09-04T10:02:00+08:00", code="000003", mode="sample")
    add_run(repo, "future", "2026-09-04T14:58:00+08:00", price=1)

    report = ReviewCenter(repo.db_path).report(
        "limit-up-ambush", "2026-09-03", "2026-09-04",
        as_of=datetime.fromisoformat("2026-09-04T11:00:00+08:00"))

    assert report["scan_count"] == 3
    assert report["event_count"] == 1
    assert report["events"][0]["first_run_id"] == "first"
    assert report["events"][0]["last_observed_price"] == 10
    assert "mixed_strategy_versions" in report["events"][0]["quality_flags"]
    assert report["days"][0] == {"date": "2026-09-03", "scan_count": 1,
                                 "event_count": 0, "status": "zero_signals"}


def test_observed_performance_is_separate_from_close_and_invalid_prices(tmp_path):
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "a", "2026-09-04T09:40:00+08:00", price=10)
    add_run(repo, "b", "2026-09-04T10:00:00+08:00", price=11)
    add_run(repo, "bad", "2026-09-04T09:40:00+08:00", code="000002", price=0)
    add_run(repo, "single", "2026-09-04T09:40:00+08:00", code="000003")
    report = ReviewCenter(repo.db_path).report("limit-up-ambush", "2026-09-04", "2026-09-04")

    metric = report["metrics"]["last_observed_positive_rate"]
    assert (metric["success_count"], metric["eligible_count"], metric["unknown_count"]) == (1, 1, 2)
    assert metric["rate_pct"] == 100
    assert report["observed_returns"]["mean_pct"] == 10
    bad = next(e for e in report["events"] if e["code"] == "000002")
    assert bad["last_observed_return_pct"] is None
    assert "invalid_first_price" in bad["quality_flags"]
    assert report["metrics"]["close_positive_rate"]["unknown_count"] == 3


def test_readonly_review_api_exposes_metrics_and_validates_ranges(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    monkeypatch.setattr(main, "repository", repo)
    client = TestClient(main.app)
    response = client.get("/api/review/summary", params={
        "strategy_id": "limit-up-ambush", "date_from": "2026-09-04", "date_to": "2026-09-04"})
    assert response.status_code == 200
    assert response.json()["event_count"] == 1
    assert client.get("/api/review/summary", params={
        "strategy_id": "limit-up-ambush", "date_from": "2026-02-30", "date_to": "2026-09-04"}).status_code == 422
    assert client.get("/api/review/summary", params={
        "strategy_id": "limit-up-ambush", "date_from": "2026-09-04", "date_to": "2026-09-03"}).status_code == 422
    assert client.get("/api/review/summary", params={
        "strategy_id": "p1-sector-resonance", "date_from": "2026-09-04", "date_to": "2026-09-04"}).status_code == 422


def test_reports_are_idempotent_and_revisions_preserve_previous_evidence(tmp_path):
    from app.review_reports import ReviewReportArchive

    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    center = ReviewCenter(repo.db_path)
    archive = ReviewReportArchive(tmp_path / "reports.db")
    assert archive.list_reports() == []
    assert not (tmp_path / "reports.db").exists()
    initial = center.report("limit-up-ambush", "2026-09-04", "2026-09-04")
    first = archive.save(initial, period="daily")
    repeat = archive.save({**initial, "as_of": "2026-09-05T18:00:00+08:00"}, period="daily")
    assert repeat["report_id"] == first["report_id"]
    add_run(repo, "later", "2026-09-04T14:58:00+08:00", price=9)
    second = archive.save(center.report("limit-up-ambush", "2026-09-04", "2026-09-04"), period="daily")
    assert second["revision"] == 2
    assert len(archive.list_reports()) == 2
    assert archive.get(first["report_id"])["report"]["events"][0]["last_observed_return_pct"] is None
    assert archive.get(second["report_id"])["report"]["events"][0]["last_observed_return_pct"] == -10
    assert archive.get("missing") is None


def test_report_generation_and_api_leave_source_unchanged(tmp_path, monkeypatch):
    from hashlib import sha256
    from fastapi.testclient import TestClient
    from app import main
    from scripts.generate_review_report import generate_reports

    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "v1", "2026-09-04T14:50:00+08:00", strategy_id="fishing-reversal")
    source_hash = sha256(repo.db_path.read_bytes()).hexdigest()
    generated = generate_reports(repo.db_path, tmp_path / "review_reports.db",
                                 period="daily", date_from="2026-09-04", date_to="2026-09-04")
    assert len(generated) == 2
    assert sha256(repo.db_path.read_bytes()).hexdigest() == source_hash
    monkeypatch.setattr(main, "repository", repo)
    client = TestClient(main.app)
    response = client.get("/api/review/reports", params={"strategy_id": "fishing-reversal"})
    assert response.status_code == 200
    assert len(response.json()["reports"]) == 1
    item = response.json()["reports"][0]
    detail = client.get("/api/review/reports/" + item["report_id"])
    assert detail.status_code == 200
    assert detail.json()["report"]["event_count"] == 1
    assert client.get("/api/review/reports/missing").status_code == 404
    with pytest.raises(ValueError, match="separate"):
        generate_reports(repo.db_path, repo.db_path, period="daily",
                         date_from="2026-09-04", date_to="2026-09-04")


def test_reports_preserve_trigger_evidence_and_disclose_unobserved_dates(tmp_path):
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    add_run(repo, "later", "2026-09-04T10:00:00+08:00", price=11)
    report = ReviewCenter(repo.db_path).report("limit-up-ambush", "2026-09-03", "2026-09-04")
    assert report["events"][0]["trigger_signal"]["snapshot"]["price"] == 10
    assert report["events"][0]["trigger_signal"]["reason"] == "测试信号"
    assert report["coverage"]["dates_without_run_evidence"] == ["2026-09-03"]
    assert report["coverage"]["calendar_verified"] is False
    with pytest.raises(ValueError):
        ReviewCenter(repo.db_path).report("limit-up-ambush", "0001-01-01", "0001-01-01")
