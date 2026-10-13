"""Regression coverage for date-scoped Top-N board classification."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from analysis.pipeline import mark_top_n_boards
from storage.connection import session


def _seed_metric(conn, board: str, metric_date: str, effective_items: float) -> None:
    conn.execute(
        """
        INSERT INTO daily_metrics (
            board, date, effective_item_count, metric_version,
            lexicon_version, board_dict_version
        ) VALUES (?, ?, ?, 'test', 'test', 'test')
        """,
        (board, metric_date, effective_items),
    )


def _seed_trading_dates(conn, dates: list[str]) -> None:
    conn.executemany(
        "INSERT INTO sector_prices (board, date, close) VALUES ('Market', ?, 1.0)",
        [(metric_date,) for metric_date in dates],
    )


def _trading_dates(count: int) -> list[str]:
    start = date(2024, 1, 1)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(count)]


def _top_boards(conn, metric_date: str) -> set[str]:
    rows = conn.execute(
        "SELECT board FROM daily_metrics WHERE date = ? AND is_top_board = 1",
        (metric_date,),
    ).fetchall()
    return {row["board"] for row in rows}


def test_top_n_for_date_ignores_future_volume(tmp_path: Path) -> None:
    db_path = tmp_path / "top_n.db"
    dates = _trading_dates(25)
    target_date = dates[19]

    with session(db_path) as conn:
        _seed_trading_dates(conn, dates)
        for metric_date in dates[:20]:
            _seed_metric(conn, "Alpha", metric_date, 6.0)
            _seed_metric(conn, "Beta", metric_date, 5.0)
            _seed_metric(conn, "Future", metric_date, 0.0)
        for metric_date in dates[20:]:
            _seed_metric(conn, "Alpha", metric_date, 0.0)
            _seed_metric(conn, "Beta", metric_date, 0.0)
            _seed_metric(conn, "Future", metric_date, 1000.0)
        conn.commit()

        mark_top_n_boards(conn, metric_dates=[target_date], top_n=1)

        assert _top_boards(conn, target_date) == {"Alpha"}
        assert _top_boards(conn, dates[24]) == set()


def test_top_n_requires_twenty_known_trading_days(tmp_path: Path) -> None:
    db_path = tmp_path / "top_n.db"
    dates = _trading_dates(19)
    target_date = dates[-1]

    with session(db_path) as conn:
        _seed_trading_dates(conn, dates)
        for metric_date in dates:
            _seed_metric(conn, "Alpha", metric_date, 10.0)
            _seed_metric(conn, "Beta", metric_date, 10.0)
        conn.commit()

        mark_top_n_boards(conn, metric_dates=[target_date], top_n=1)

        assert _top_boards(conn, target_date) == set()


def test_top_n_falls_back_to_forum_observation_dates_without_prices(tmp_path: Path) -> None:
    db_path = tmp_path / "top_n-no-prices.db"
    dates = _trading_dates(20)
    target_date = dates[-1]

    with session(db_path) as conn:
        for metric_date in dates:
            _seed_metric(conn, "Alpha", metric_date, 6.0)
            _seed_metric(conn, "Beta", metric_date, 5.0)
        conn.commit()

        mark_top_n_boards(conn, metric_dates=[target_date], top_n=1)

        assert _top_boards(conn, target_date) == {"Alpha"}


def test_rerunning_for_a_date_clears_a_stale_top_board_flag(tmp_path: Path) -> None:
    db_path = tmp_path / "top_n.db"
    dates = _trading_dates(20)
    target_date = dates[-1]

    with session(db_path) as conn:
        _seed_trading_dates(conn, dates)
        for metric_date in dates:
            _seed_metric(conn, "Alpha", metric_date, 6.0)
            _seed_metric(conn, "Beta", metric_date, 5.0)
        conn.commit()

        mark_top_n_boards(conn, metric_dates=[target_date], top_n=1)
        assert _top_boards(conn, target_date) == {"Alpha"}

        conn.execute(
            "UPDATE daily_metrics SET effective_item_count = 5.0 WHERE board = 'Alpha'",
        )
        conn.execute(
            "UPDATE daily_metrics SET effective_item_count = 6.0 WHERE board = 'Beta'",
        )
        conn.commit()

        mark_top_n_boards(conn, metric_dates=[target_date], top_n=1)

        assert _top_boards(conn, target_date) == {"Beta"}


def test_equal_totals_use_alphabetical_tie_break_and_support_positional_top_n(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "top_n.db"
    dates = _trading_dates(20)
    target_date = dates[-1]

    with session(db_path) as conn:
        _seed_trading_dates(conn, dates)
        for metric_date in dates:
            _seed_metric(conn, "Beta", metric_date, 5.0)
            _seed_metric(conn, "Alpha", metric_date, 5.0)
        conn.commit()

        mark_top_n_boards(conn, 1)

        assert _top_boards(conn, target_date) == {"Alpha"}
