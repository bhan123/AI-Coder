from datetime import date, timedelta

import pytest

from app.review_reports import ReviewReportArchive


def report(day, **updates):
    return {"strategy_id": "limit-up-ambush", "date_from": day, "date_to": day,
            "status": "incomplete", "event_count": 1, "as_of": day + "T16:30:00+08:00", **updates}


def test_archive_filters_full_history_before_pagination(tmp_path):
    archive = ReviewReportArchive(tmp_path / "archive.db")
    for i in range(60):
        archive.save(report((date(2026, 1, 1) + timedelta(days=i)).isoformat()), period="daily")
    old = archive.search(date_from="2026-01-01", date_to="2026-01-03", limit=2)
    assert old["total"] == 3
    assert len(old["reports"]) == 2
    assert old["has_more"] is True
    following = archive.search(date_from="2026-01-01", date_to="2026-01-03", limit=2, offset=2)
    assert len(following["reports"]) == 1
    assert following["has_more"] is False
    assert {r["date_from"] for r in old["reports"] + following["reports"]} == {"2026-01-01", "2026-01-02", "2026-01-03"}


def test_archive_supports_period_latest_revision_and_overlapping_week(tmp_path):
    archive = ReviewReportArchive(tmp_path / "archive.db")
    first = archive.save(report("2026-09-04"), period="daily")
    second = archive.save(report("2026-09-04", event_count=2), period="daily")
    archive.save(report("2026-09-01", date_to="2026-09-07"), period="weekly")
    archive.save(report("2026-09-04", strategy_id="fishing-reversal"), period="daily")
    latest = archive.search(strategy_id="limit-up-ambush", date_from="2026-09-04", date_to="2026-09-04", latest_only=True)
    assert latest["total"] == 2
    assert second["report_id"] in {r["report_id"] for r in latest["reports"]}
    assert first["report_id"] not in {r["report_id"] for r in latest["reports"]}
    all_daily = archive.search(strategy_id="limit-up-ambush", period="daily")
    assert all_daily["total"] == 2
    assert archive.search(period="weekly", date_from="2026-09-04", date_to="2026-09-04")["total"] == 1


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 201}, {"limit": True}, {"offset": -1}, {"offset": 0.5},
    {"date_from": "2026-01-01"}, {"date_from": "2026-02-30", "date_to": "2026-03-01"},
    {"date_from": "2026-09-04", "date_to": "2026-09-03"}, {"period": "monthly"},
    {"strategy_id": "p1-sector-resonance"},
])
def test_archive_rejects_invalid_search_before_opening_file(tmp_path, params):
    archive = ReviewReportArchive(tmp_path / "missing.db")
    with pytest.raises(ValueError):
        archive.search(**params)
    assert not archive.path.exists()


def test_archive_api_applies_filters_and_returns_readonly_page(tmp_path, monkeypatch):
    from hashlib import sha256
    from fastapi.testclient import TestClient
    from app import main
    from app.repository import StrategyRepository
    repo = StrategyRepository(str(tmp_path / "source.db"))
    monkeypatch.setattr(main, "repository", repo)
    archive = ReviewReportArchive(tmp_path / "review_reports.db")
    old = archive.save(report("2026-09-04"), period="daily")
    latest = archive.save(report("2026-09-04", event_count=2), period="daily")
    archive.save(report("2026-09-05"), period="daily")
    before = sha256(archive.path.read_bytes()).hexdigest()
    client = TestClient(main.app)
    response = client.get('/api/review/reports', params={"date_from":"2026-09-04", "date_to":"2026-09-04", "period":"daily", "latest_only":"true", "limit":1})
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["reports"][0]["report_id"] == latest["report_id"]
    assert client.get('/api/review/reports/' + old["report_id"]).status_code == 200
    for params in ({"date_from":"2026-09-04"}, {"offset":-1}, {"period":"monthly"}, {"date_from":"2026-09-05", "date_to":"2026-09-04"}):
        assert client.get('/api/review/reports', params=params).status_code == 422
    assert sha256(archive.path.read_bytes()).hexdigest() == before
