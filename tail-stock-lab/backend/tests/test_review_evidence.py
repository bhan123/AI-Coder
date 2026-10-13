from datetime import datetime

import pytest

from app.review_evidence import ClosingEvidence, evaluate_close


def evidence(**updates):
    return ClosingEvidence.model_validate({
        "code": "000001", "trade_date": "2026-09-04", "close": "10.50",
        "limit_up": "11.00", "day_high": "11.00", "source": "test-feed",
        "source_reference": "test-fixture-1", "price_at": "2026-09-04T15:00:00+08:00",
        "fetched_at": "2026-09-04T16:00:00+08:00", **updates,
    })


def event(**updates):
    return {"code": "000001", "date": "2026-09-04", "first_price": 10,
            "first_at": "2026-09-04T09:40:00+08:00", **updates}


def test_day_high_touch_does_not_prove_post_alert_touch():
    result = evaluate_close(event(), evidence())
    assert result["close_positive"] is True
    assert result["close_limit"] is False
    assert result["close_return_pct"] == 5
    assert result["post_alert_limit"] is None
    assert "touch_order_unknown" in result["quality_flags"]


@pytest.mark.parametrize("updates", [
    {"price_at": "2026-09-04T14:58:00+08:00"},
    {"price_at": "2026-09-03T15:00:00+08:00"},
    {"price_at": "2026-09-04T15:00:00"},
    {"fetched_at": "2026-09-04T14:59:00+08:00"},
    {"day_high": "10.00"}, {"limit_up": "10.00"},
    {"close": "NaN"}, {"price_basis": "qfq"},
])
def test_inconsistent_or_intraday_evidence_is_rejected(updates):
    with pytest.raises(ValueError):
        evidence(**updates)


@pytest.mark.parametrize("updates, expected", [
    ({"close": "11.00"}, True),
    ({"day_high": "10.60"}, False),
    ({"limit_touch_times": ["2026-09-04T09:35:00+08:00"]}, None),
    ({"limit_touch_times": ["2026-09-04T09:40:00+08:00"]}, None),
    ({"limit_touch_times": ["2026-09-04T10:00:00+08:00"]}, True),
    ({"limit_up": None}, None),
])
def test_post_alert_touch_requires_ordered_evidence(updates, expected):
    assert evaluate_close(event(), evidence(**updates))["post_alert_limit"] is expected


def test_invalid_entry_and_mismatched_security_do_not_create_returns():
    assert evaluate_close(event(first_price=0), evidence())["close_positive"] is None
    assert evaluate_close(event(first_price=None), evidence())["close_return_pct"] is None
    with pytest.raises(ValueError):
        evaluate_close(event(code="000002"), evidence())
    with pytest.raises(ValueError):
        evidence(limit_touch_times=["2026-09-03T10:00:00+08:00"])


def test_evidence_store_preserves_corrections_and_receipt_time(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore

    now = datetime.fromisoformat("2026-09-04T16:01:00+08:00")
    store = ClosingEvidenceStore(tmp_path / "evidence.db", clock=lambda: now)
    assert store.latest("000001", "2026-09-04", as_of=now) is None
    assert not (tmp_path / "evidence.db").exists()
    first = store.record(evidence())
    assert store.record(evidence()) == first
    assert store.latest("000001", "2026-09-04", as_of=datetime.fromisoformat("2026-09-04T16:00:00+08:00")) is None
    now = datetime.fromisoformat("2026-09-04T17:01:00+08:00")
    second = store.record(evidence(close="10.40", fetched_at="2026-09-04T17:00:00+08:00"))
    assert first != second
    historical = store.latest("000001", "2026-09-04", as_of=datetime.fromisoformat("2026-09-04T16:30:00+08:00"))
    assert historical["evidence_id"] == first
    assert store.latest("000001", "2026-09-04", as_of=now)["evidence_id"] == second


def test_report_uses_available_close_without_overwriting_intraday_observation(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore
    from app.review_center import ReviewCenter
    from app.repository import StrategyRepository
    from test_review_center import add_run

    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    add_run(repo, "last", "2026-09-04T14:58:00+08:00", price=9)
    now = datetime.fromisoformat("2026-09-04T16:01:00+08:00")
    store = ClosingEvidenceStore(tmp_path / "review_evidence.db", clock=lambda: now)
    evidence_id = store.record(evidence(close="11.00"))
    center = ReviewCenter(repo.db_path)
    old = center.report("limit-up-ambush", "2026-09-04", "2026-09-04",
                        as_of=datetime.fromisoformat("2026-09-04T16:00:00+08:00"))
    assert old["metrics"]["close_positive_rate"]["unknown_count"] == 1
    report = center.report("limit-up-ambush", "2026-09-04", "2026-09-04", as_of=now)
    assert report["metrics"]["close_positive_rate"]["rate_pct"] == 100
    row = report["events"][0]
    assert row["close_return_pct"] == 10
    assert row["last_observed_return_pct"] == -10
    assert row["closing_evidence"]["evidence_id"] == evidence_id
    assert "close_unverified" not in row["quality_flags"]


def test_correction_can_return_to_previous_value_without_losing_revision(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore
    now = datetime.fromisoformat("2026-09-04T18:00:00+08:00")
    store = ClosingEvidenceStore(tmp_path / "evidence.db", clock=lambda: now)
    first = store.record(evidence())
    store.record(evidence(close="10.40"))
    restored = store.record(evidence())
    assert restored != first
    assert store.latest("000001", "2026-09-04", as_of=now)["evidence_id"] == restored


def test_conflicting_sources_remain_unknown_in_report(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore
    from app.review_center import ReviewCenter
    from app.repository import StrategyRepository
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    now = datetime.fromisoformat("2026-09-04T18:00:00+08:00")
    store = ClosingEvidenceStore(tmp_path / "review_evidence.db", clock=lambda: now)
    store.record(evidence())
    store.record(evidence(source="second-feed", close="10.40"))
    report = ReviewCenter(repo.db_path).report("limit-up-ambush", "2026-09-04", "2026-09-04", as_of=now)
    assert report["metrics"]["close_positive_rate"]["unknown_count"] == 1
    assert "closing_source_conflict" in report["events"][0]["quality_flags"]


def test_arriving_close_creates_report_revision_without_rewriting_old_report(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore
    from app.review_reports import ReviewReportArchive
    from app.repository import StrategyRepository
    from scripts.generate_review_report import generate_reports
    from test_review_center import add_run
    repo = StrategyRepository(str(tmp_path / "source.db"))
    add_run(repo, "first", "2026-09-04T09:40:00+08:00")
    archive_path = tmp_path / "review_reports.db"
    initial = generate_reports(repo.db_path, archive_path, period="daily",
                               date_from="2026-09-04", date_to="2026-09-04")[1]
    ClosingEvidenceStore(tmp_path / "review_evidence.db").record(evidence(close="11.00"))
    revised = generate_reports(repo.db_path, archive_path, period="daily",
                               date_from="2026-09-04", date_to="2026-09-04")[1]
    archive = ReviewReportArchive(archive_path)
    assert revised["revision"] == 2
    assert archive.get(initial["report_id"])["report"]["metrics"]["close_limit_rate"]["rate_pct"] is None
    assert archive.get(revised["report_id"])["report"]["metrics"]["close_limit_rate"]["rate_pct"] == 100


def test_fetch_window_validation_and_repeated_fetch_do_not_create_revision(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore
    for started in ("2026-09-04T16:01:00+08:00", "2026-09-04T15:59:00"):
        with pytest.raises(ValueError):
            evidence(fetch_started_at=started)
    now = datetime.fromisoformat("2026-09-04T18:00:00+08:00")
    store = ClosingEvidenceStore(tmp_path / "evidence.db", clock=lambda: now)
    first = store.record(evidence(fetch_started_at="2026-09-04T15:59:00+08:00"))
    repeated = store.record(evidence(fetch_started_at="2026-09-04T16:59:00+08:00", fetched_at="2026-09-04T17:00:00+08:00"))
    assert repeated == first


def test_delayed_older_fetch_cannot_replace_newer_source_evidence(tmp_path):
    from app.review_evidence_store import ClosingEvidenceStore
    now = datetime.fromisoformat("2026-09-04T18:00:00+08:00")
    store = ClosingEvidenceStore(tmp_path / "evidence.db", clock=lambda: now)
    newest = store.record(evidence(close="10.40", fetched_at="2026-09-04T17:00:00+08:00"))
    with pytest.raises(ValueError, match="older"):
        store.record(evidence())
    assert store.latest("000001", "2026-09-04", as_of=now)["evidence_id"] == newest
