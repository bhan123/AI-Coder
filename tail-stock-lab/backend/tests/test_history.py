from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from math import nan

from fastapi.testclient import TestClient

from app import main
from app.models import FactorContribution, MarketSnapshot, PaperTrade, Signal, StrategyRun, T1MarketReview, T1PricePoint
from app.repository import StrategyRepository
from app.t1_collector import T1ReviewCollector


def _signal(code: str, name: str, score: float = 70.0) -> Signal:
    return Signal(
        code=code, name=name, score=score, eligible=True,
        reason="测试用信号", risk_level="low", factors=[], snapshot=MarketSnapshot(
            code=code, name=name, price=10.0, pct_change=-2.0, day_low=9.8,
            turnover_rate=2.0, volume_ratio=1.0, market_pct_change=-0.5,
            captured_at=datetime(2026, 8, 3, 14, 50),
        ),
    )


def _run(
    run_id: str,
    strategy_id: str,
    observed_at: datetime,
    *,
    signals: list[Signal] | None = None,
    capture_origin: str = "scheduled",
) -> StrategyRun:
    return StrategyRun(
        run_id=run_id, strategy_id=strategy_id, version="1.0.0",
        observed_at=observed_at, mode="live", data_source="live",
        execution_status="tradable", universe_size=100, signals=signals or [],
        capture_origin=capture_origin,
    )


def _open_repo() -> tuple[StrategyRepository, str]:
    fd, path = tempfile.mkstemp(prefix="tail-stock-lab-history-", suffix=".db", dir=os.path.dirname(__file__))
    os.close(fd)
    return StrategyRepository(db_path=path), path


def _close(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def test_list_runs_returns_metadata_with_signal_count_desc() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("r1", "fishing-reversal", datetime(2026, 8, 1, 14, 50),
                           signals=[_signal("000001", "A"), _signal("000002", "B")]))
        repo.save_run(_run("r2", "fishing-reversal", datetime(2026, 8, 3, 14, 50),
                           signals=[_signal("000003", "C")]))
        repo.save_run(_run("r3", "p1-sector-resonance", datetime(2026, 8, 3, 14, 50)))

        rows = repo.list_runs("fishing-reversal", limit=10)

        assert [row["run_id"] for row in rows] == ["r2", "r1"]
        assert rows[0]["signal_count"] == 1
        assert rows[1]["signal_count"] == 2
        assert rows[0]["execution_status"] == "tradable"
        assert rows[0]["data_source"] == "live"
    finally:
        _close(path)


def test_alert_history_merges_repeated_scans_into_one_stock_event() -> None:
    repo, path = _open_repo()
    try:
        first = _signal("301428", "测试预警", score=82.0)
        first = first.model_copy(update={
            "snapshot": first.snapshot.model_copy(update={
                "price": 20.0,
                "pct_change": 5.0,
                "captured_at": datetime(2026, 8, 13, 9, 36),
            }),
        })
        repeated = first.model_copy(update={
            "score": 91.4,
            "snapshot": first.snapshot.model_copy(update={
                "price": 20.8,
                "pct_change": 9.2,
                "captured_at": datetime(2026, 8, 13, 9, 38),
            }),
        })
        first_run = _run(
            "alert-1", "limit-up-ambush", datetime(2026, 8, 13, 9, 36),
            signals=[first],
        )
        repeated_run = _run(
            "alert-2", "limit-up-ambush", datetime(2026, 8, 13, 9, 38),
            signals=[repeated],
        )

        repo.save_run(first_run)
        repo.record_alert_run(first_run)
        repo.save_run(repeated_run)
        repo.record_alert_run(repeated_run)

        history = repo.alert_history("limit-up-ambush", alert_date="2026-08-13")

        assert history["scan_count"] == 2
        assert history["unique_stock_count"] == 1
        assert len(history["events"]) == 1
        event = history["events"][0]
        assert event["code"] == "301428"
        assert event["first_alert_at"] == "2026-08-13T09:36:00"
        assert event["last_alert_at"] == "2026-08-13T09:38:00"
        assert event["hit_count"] == 2
        assert event["max_score"] == 91.4
        assert [point["is_alert"] for point in event["timeline"]] == [True, True]
    finally:
        _close(path)


def test_alert_history_labels_new_momentum_alerts_as_strengthening_counts() -> None:
    repo, path = _open_repo()
    try:
        signal = _signal("000001", "连续增强", score=80.0).model_copy(update={
            "factors": [FactorContribution(
                key="price_momentum", label="连续增强", value=0.5, score=10.0,
                description="最近三个快照逐次抬高",
            )],
        })
        run = _run(
            "strengthening-1", "limit-up-ambush", datetime(2026, 8, 14, 9, 40),
            signals=[signal],
        )

        repo.save_run(run)
        repo.record_alert_run(run)
        history = repo.alert_history("limit-up-ambush", alert_date="2026-08-14")

        assert history["count_semantics"] == "strengthening"
        assert history["events"][0]["count_semantics"] == "strengthening"
    finally:
        _close(path)


def test_alert_history_marks_same_day_old_and_new_count_semantics_as_mixed() -> None:
    repo, path = _open_repo()
    try:
        old_signal = _signal("000001", "跨版本预警", score=70.0)
        new_signal = old_signal.model_copy(update={
            "factors": [FactorContribution(
                key="price_momentum", label="连续增强", value=0.5, score=10.0,
                description="最近三个快照逐次抬高",
            )],
        })
        for run_id, minute, signal in (
            ("legacy", 36, old_signal), ("momentum", 40, new_signal),
        ):
            run = _run(
                run_id, "limit-up-ambush", datetime(2026, 8, 14, 9, minute),
                signals=[signal],
            )
            repo.save_run(run)
            repo.record_alert_run(run)

        history = repo.alert_history("limit-up-ambush", alert_date="2026-08-14")

        assert history["count_semantics"] == "mixed"
        assert history["events"][0]["count_semantics"] == "mixed"
    finally:
        _close(path)


def test_alert_outcome_tracks_post_alert_path_and_board_limit() -> None:
    repo, path = _open_repo()
    try:
        signal = _signal("301428", "创业板预警", score=82.0)
        signal = signal.model_copy(update={
            "snapshot": signal.snapshot.model_copy(update={
                "price": 20.0,
                "pct_change": 5.0,
                "captured_at": datetime(2026, 8, 13, 9, 36),
            }),
        })
        run = _run(
            "alert-path", "limit-up-ambush", datetime(2026, 8, 13, 9, 36),
            signals=[signal],
        )
        repo.save_run(run)
        repo.record_alert_run(run)

        repo.update_alert_outcomes(
            "limit-up-ambush",
            datetime(2026, 8, 13, 10, 0),
            [signal.snapshot.model_copy(update={"price": 18.8, "pct_change": -1.3})],
        )
        repo.update_alert_outcomes(
            "limit-up-ambush",
            datetime(2026, 8, 13, 10, 10),
            [signal.snapshot.model_copy(update={"price": 23.0, "pct_change": 19.85})],
            finalize=True,
        )

        history = repo.alert_history("limit-up-ambush", alert_date="2026-08-13")
        event = history["events"][0]
        assert event["status"] == "hit_limit"
        assert event["first_limit_up_at"] == "2026-08-13T10:10:00"
        assert event["max_pct"] == 19.85
        assert event["max_gain_from_alert_pct"] == 15.0
        assert event["max_drawdown_from_alert_pct"] == -6.0
        assert len(event["timeline"]) == 3
        assert history["hit_limit_count"] == 1
        assert history["hit_limit_rate"] == 100.0
    finally:
        _close(path)


def test_existing_alert_scans_are_backfilled_when_event_storage_is_added() -> None:
    repo, path = _open_repo()
    try:
        signal = _signal("688167", "历史预警", score=87.1)
        signal = signal.model_copy(update={
            "snapshot": signal.snapshot.model_copy(update={
                "price": 30.0,
                "pct_change": 9.14,
                "captured_at": datetime(2026, 8, 13, 9, 40),
            }),
        })
        repo.save_run(_run(
            "legacy-alert", "limit-up-ambush", datetime(2026, 8, 13, 9, 40),
            signals=[signal],
        ))

        reopened = StrategyRepository(db_path=path)
        history = reopened.alert_history("limit-up-ambush", alert_date="2026-08-13")

        assert history["unique_stock_count"] == 1
        assert history["events"][0]["code"] == "688167"
        assert history["events"][0]["hit_count"] == 1
    finally:
        _close(path)


def test_alert_history_api_exposes_daily_summary_and_persistence_filter(monkeypatch) -> None:
    repo, path = _open_repo()
    try:
        signal = _signal("000001", "持续预警", score=80.0)
        for minute in (36, 38, 40):
            observed_at = datetime(2026, 8, 13, 9, minute)
            current = signal.model_copy(update={
                "snapshot": signal.snapshot.model_copy(update={
                    "price": 10.0 + minute / 100,
                    "pct_change": 5.0 + minute / 100,
                    "captured_at": observed_at,
                }),
            })
            run = _run(
                f"persistent-{minute}", "limit-up-ambush", observed_at,
                signals=[current],
            )
            repo.save_run(run)
            repo.record_alert_run(run)
        monkeypatch.setattr(main, "repository", repo)

        response = TestClient(main.app).get(
            "/api/strategies/limit-up-ambush/alert-history",
            params={"date": "2026-08-13", "persistent_only": "true"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["available_dates"] == ["2026-08-13"]
        assert payload["scan_count"] == 3
        assert payload["persistent_count"] == 1
        assert payload["events"][0]["hit_count"] == 3
    finally:
        _close(path)


def test_list_runs_filters_by_date_range() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("a", "p3-platform-breakout", datetime(2026, 7, 31, 14, 50)))
        repo.save_run(_run("b", "p3-platform-breakout", datetime(2026, 8, 1, 14, 50)))
        repo.save_run(_run("c", "p3-platform-breakout", datetime(2026, 8, 3, 14, 50)))

        rows = repo.list_runs("p3-platform-breakout", date_from="2026-08-01", date_to="2026-08-03")
        assert [row["run_id"] for row in rows] == ["c", "b"]
    finally:
        _close(path)


def test_list_runs_excludes_sample_mode_by_default() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(StrategyRun(
            run_id="sample", strategy_id="fishing-reversal", version="1.0.0",
            observed_at=datetime(2026, 8, 3, 14, 50), mode="sample", data_source="sample",
            execution_status="sample", universe_size=1, signals=[],
        ))
        repo.save_run(_run("live", "fishing-reversal", datetime(2026, 8, 3, 14, 50)))

        rows = repo.list_runs("fishing-reversal")
        assert [row["run_id"] for row in rows] == ["live"]
    finally:
        _close(path)


def test_history_lists_only_scheduled_snapshots() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("official", "fishing-reversal", datetime(2026, 8, 3, 14, 50)))
        repo.save_run(_run(
            "manual-check", "fishing-reversal", datetime(2026, 8, 3, 15, 10),
            capture_origin="manual",
        ))

        rows = repo.list_runs("fishing-reversal")

        assert [row["run_id"] for row in rows] == ["official"]
    finally:
        _close(path)


def test_latest_t1_reviews_return_only_the_latest_v1_formal_recommendations() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("v1-prior", "fishing-reversal", datetime(2026, 8, 10, 14, 50),
                           signals=[_signal("000001", "旧推荐")]))
        repo.save_run(_run("v1-latest", "fishing-reversal", datetime(2026, 8, 11, 14, 50),
                           signals=[_signal("000002", "昨日推荐")]))
        repo.save_run(_run("p1-latest", "p1-sector-resonance", datetime(2026, 8, 11, 14, 50),
                           signals=[_signal("000003", "隐藏策略")]))
        trade = PaperTrade(
            code="000001", name="旧推荐", entry_price=10, exit_price=10.1, net_return_pct=0.85,
            touched_breakeven=True, profitable_exit=True, exit_reason="morning_cutoff",
            session_low_price=9.9, session_high_price=10.2,
        )
        repo.save_t1_outcome("v1-prior", "2026-08-11", trade)
        repo.save_t1_outcome("v1-latest", "2026-08-12", trade.model_copy(update={"code": "000002", "name": "昨日推荐"}))
        repo.save_t1_outcome("p1-latest", "2026-08-12", trade.model_copy(update={"code": "000003", "name": "隐藏策略"}))

        review_date, reviews = repo.latest_t1_reviews("fishing-reversal")

        assert review_date == "2026-08-12"
        assert len(reviews) == 1
        assert reviews[0]["recommendation_at"] == "2026-08-11T14:50:00"
        assert reviews[0]["trade"].code == "000002"
    finally:
        _close(path)


def test_t1_review_api_exposes_the_latest_formal_review_day(monkeypatch) -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("v1-review", "fishing-reversal", datetime(2026, 8, 11, 14, 50),
                           signals=[_signal("000002", "昨日推荐")]))
        repo.save_t1_outcome("v1-review", "2026-08-12", PaperTrade(
            code="000002", name="昨日推荐", entry_price=10, exit_price=10.1, net_return_pct=0.85,
            touched_breakeven=True, profitable_exit=True, exit_reason="morning_cutoff",
            session_low_price=9.9, session_high_price=10.2,
        ))
        monkeypatch.setattr(main, "repository", repo)

        response = TestClient(main.app).get("/api/strategies/fishing-reversal/t1-review/latest")

        assert response.status_code == 200
        payload = response.json()
        assert payload["review_date"] == "2026-08-12"
        assert payload["reviews"][0]["recommendation_at"].startswith("2026-08-11")
        assert payload["reviews"][0]["trade"]["session_high_price"] == 10.2
    finally:
        _close(path)


def test_t1_review_collector_persists_the_observed_chart_without_changing_rule_exit() -> None:
    repo, path = _open_repo()
    try:
        signal = _signal("000002", "Review stock")
        repo.save_run(_run("review-run", "fishing-reversal", datetime(2026, 8, 11, 14, 50), signals=[signal]))
        original_trade = PaperTrade(
            code="000002", name="Review stock", entry_price=10, exit_price=9.7, net_return_pct=-3.15,
            touched_breakeven=False, profitable_exit=False, exit_reason="stop_loss",
        )
        repo.save_t1_outcome("review-run", "2026-08-12", original_trade)

        class Provider:
            def fetch_review(self, supplied_signal):
                assert supplied_signal.code == "000002"
                return T1MarketReview(
                    observed_at=datetime(2026, 8, 12, 14, 50), open_price=9.7,
                    low_price=9.7, high_price=10.6, last_price=10.5,
                    points=[T1PricePoint(time="0930", price=9.7), T1PricePoint(time="1450", price=10.5)],
                )

        collected = T1ReviewCollector(repo, Provider()).collect_due(datetime(2026, 8, 12, 14, 50))
        _, reviews = repo.latest_t1_reviews("fishing-reversal")

        assert len(collected) == 1
        assert reviews[0]["trade"].exit_price == 9.7
        assert reviews[0]["trade"].exit_reason == "stop_loss"
        assert reviews[0]["trade"].market_review.high_price == 10.6
        assert reviews[0]["trade"].market_review.points[-1].time == "1450"
    finally:
        _close(path)


def test_latest_scheduled_snapshot_ignores_a_newer_manual_check() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("official", "fishing-reversal", datetime(2026, 8, 3, 14, 50)))
        repo.save_run(_run(
            "manual-check", "fishing-reversal", datetime(2026, 8, 3, 15, 10),
            capture_origin="manual",
        ))

        latest = repo.latest_scheduled_run("fishing-reversal")

        assert latest is not None
        assert latest.run_id == "official"
    finally:
        _close(path)


def test_legacy_tail_window_record_is_migrated_to_scheduled_origin() -> None:
    fd, path = tempfile.mkstemp(prefix="tail-stock-lab-legacy-", suffix=".db", dir=os.path.dirname(__file__))
    os.close(fd)
    try:
        with sqlite3.connect(path) as conn:
            conn.executescript("""
                CREATE TABLE strategy_runs (
                    run_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    universe_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    data_source TEXT NOT NULL DEFAULT 'unknown',
                    execution_status TEXT NOT NULL DEFAULT 'sample'
                );
            """)
            conn.execute(
                """INSERT INTO strategy_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                ("old-official", "fishing-reversal", "1.0.0", "2026-08-03T14:50:02+08:00",
                 "live", 4988, "2026-08-03T14:50:02+08:00", "live", "tradable"),
            )

        repo = StrategyRepository(db_path=path)
        rows = repo.list_runs("fishing-reversal")

        assert [row["run_id"] for row in rows] == ["old-official"]
        assert rows[0]["capture_origin"] == "scheduled"
    finally:
        _close(path)


def test_list_runs_excludes_legacy_sample_status_even_when_mode_is_live() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(StrategyRun(
            run_id="legacy-sample", strategy_id="fishing-reversal", version="1.0.0",
            observed_at=datetime(2026, 8, 3, 14, 50), mode="live", data_source="unknown",
            execution_status="sample", universe_size=1, signals=[],
        ))
        repo.save_run(_run("real-live", "fishing-reversal", datetime(2026, 8, 3, 14, 50)))

        rows = repo.list_runs("fishing-reversal")

        assert [row["run_id"] for row in rows] == ["real-live"]
    finally:
        _close(path)


def test_list_recent_runs_all_strategies_returns_cross_strategy_view() -> None:
    repo, path = _open_repo()
    try:
        repo.save_run(_run("v1", "fishing-reversal", datetime(2026, 8, 3, 14, 50)))
        repo.save_run(_run("p1", "p1-sector-resonance", datetime(2026, 8, 3, 14, 50)))
        repo.save_run(_run("old", "fishing-reversal", datetime(2026, 7, 30, 14, 50)))

        rows = repo.list_recent_runs_all_strategies()
        run_ids = {row["run_id"] for row in rows}
        assert {"v1", "p1", "old"}.issubset(run_ids)
        assert rows[0]["observed_at"] >= rows[-1]["observed_at"]
    finally:
        _close(path)


def test_get_run_round_trips_full_signals() -> None:
    repo, path = _open_repo()
    try:
        run = _run(
            "with-signals", "fishing-reversal", datetime(2026, 8, 3, 14, 50),
            signals=[_signal("000001", "A", score=82.5), _signal("000002", "B", score=71.0)],
        )
        repo.save_run(run)

        loaded = repo.get_run("with-signals")
        assert loaded is not None
        assert loaded.run_id == "with-signals"
        assert len(loaded.signals) == 2
        assert loaded.signals[0].code == "000001"
        assert loaded.signals[0].score == 82.5
        assert loaded.signals[1].score == 71.0
    finally:
        _close(path)


def test_get_run_returns_none_for_unknown_id() -> None:
    repo, path = _open_repo()
    try:
        assert repo.get_run("does-not-exist") is None
    finally:
        _close(path)


def test_snapshot_with_missing_volume_ratio_is_saved_as_zero() -> None:
    """缺失量比不能让整批正式采集因 SQLite 的 NOT NULL 约束失败。"""
    repo, path = _open_repo()
    try:
        snapshot = MarketSnapshot(
            code="000001", name="测试股", price=10.0, pct_change=1.0, day_low=9.8,
            turnover_rate=2.0, volume_ratio=nan, market_pct_change=0.2,
            captured_at=datetime(2026, 8, 5, 14, 50),
        )
        run = _run("missing-volume-ratio", "fishing-reversal", datetime(2026, 8, 5, 14, 50))

        repo.save_run(run, snapshots=[snapshot])

        saved = repo.snapshots_for_run(run.run_id)
        assert saved[0].volume_ratio == 0.0
    finally:
        _close(path)


def test_historical_run_api_rejects_a_sample_record(monkeypatch) -> None:
    """A hidden sample run must not be retrievable through the public history detail API."""
    repo, path = _open_repo()
    try:
        repo.save_run(StrategyRun(
            run_id="sample-detail", strategy_id="fishing-reversal", version="1.0.0",
            observed_at=datetime(2026, 8, 3, 14, 50), mode="sample", data_source="sample",
            execution_status="sample", universe_size=1, signals=[],
        ))
        monkeypatch.setattr(main, "repository", repo)

        response = TestClient(main.app).get(
            "/api/strategies/fishing-reversal/run/sample-detail"
        )

        assert response.status_code == 404
    finally:
        _close(path)
