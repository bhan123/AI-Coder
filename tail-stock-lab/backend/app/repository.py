from __future__ import annotations

import sqlite3
from pathlib import Path

from app.models import MarketSnapshot, PaperTrade, Signal, StrategyRun


class StrategyRepository:
    def __init__(self, db_path: str = "data/tail_stock_lab.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS strategy_runs (
                    run_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    capture_origin TEXT NOT NULL DEFAULT 'manual',
                    universe_size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS strategy_signals (
                    run_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    score REAL NOT NULL,
                    eligible INTEGER NOT NULL,
                    risk_level TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, code),
                    FOREIGN KEY (run_id) REFERENCES strategy_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_strategy_runs_observed ON strategy_runs(strategy_id, observed_at DESC);
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    run_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price REAL NOT NULL,
                    pct_change REAL NOT NULL,
                    day_low REAL NOT NULL,
                    turnover_rate REAL NOT NULL,
                    volume_ratio REAL NOT NULL,
                    market_pct_change REAL NOT NULL,
                    captured_at TEXT NOT NULL,
                    PRIMARY KEY (run_id, code),
                    FOREIGN KEY (run_id) REFERENCES strategy_runs(run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_market_snapshots_captured ON market_snapshots(captured_at, code);
                CREATE TABLE IF NOT EXISTS t1_outcomes (
                    run_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    outcome_date TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, code),
                    FOREIGN KEY (run_id) REFERENCES strategy_runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS alert_events (
                    strategy_id TEXT NOT NULL,
                    alert_date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    first_alert_at TEXT NOT NULL,
                    last_alert_at TEXT NOT NULL,
                    first_alert_price REAL NOT NULL,
                    first_alert_pct REAL NOT NULL,
                    last_observed_at TEXT NOT NULL,
                    latest_price REAL NOT NULL,
                    latest_pct REAL NOT NULL,
                    hit_count INTEGER NOT NULL,
                    max_score REAL NOT NULL,
                    max_price REAL NOT NULL,
                    max_pct REAL NOT NULL,
                    min_price REAL NOT NULL,
                    min_pct REAL NOT NULL,
                    first_limit_up_at TEXT,
                    status TEXT NOT NULL DEFAULT 'watching',
                    count_semantics TEXT NOT NULL DEFAULT 'matches',
                    PRIMARY KEY (strategy_id, alert_date, code)
                );
                CREATE INDEX IF NOT EXISTS idx_alert_events_date
                    ON alert_events(strategy_id, alert_date DESC, first_alert_at);
                CREATE TABLE IF NOT EXISTS alert_event_points (
                    strategy_id TEXT NOT NULL,
                    alert_date TEXT NOT NULL,
                    code TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    price REAL NOT NULL,
                    pct_change REAL NOT NULL,
                    score REAL,
                    is_alert INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (strategy_id, alert_date, code, observed_at),
                    FOREIGN KEY (strategy_id, alert_date, code)
                        REFERENCES alert_events(strategy_id, alert_date, code)
                );
            """)
            existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(strategy_runs)")}
            migrations = {
                "data_source": "TEXT NOT NULL DEFAULT 'unknown'",
                "execution_status": "TEXT NOT NULL DEFAULT 'sample'",
                "capture_origin": "TEXT NOT NULL DEFAULT 'manual'",
            }
            for column, definition in migrations.items():
                if column not in existing_columns:
                    conn.execute(f"ALTER TABLE strategy_runs ADD COLUMN {column} {definition}")
                    if column == "capture_origin":
                        conn.execute(
                            """UPDATE strategy_runs SET capture_origin = 'scheduled'
                               WHERE mode = 'live' AND execution_status = 'tradable'
                                 AND substr(observed_at, 12, 5) BETWEEN '14:48' AND '14:55'"""
                        )
            alert_columns = {row[1] for row in conn.execute("PRAGMA table_info(alert_events)")}
            if "count_semantics" not in alert_columns:
                conn.execute(
                    "ALTER TABLE alert_events ADD COLUMN count_semantics TEXT NOT NULL DEFAULT 'matches'"
                )
        if str(self.db_path) != ":memory:":
            self._backfill_alert_events()

    def _backfill_alert_events(self) -> None:
        """Build event rows for scans created before alert history existed."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT r.run_id
                   FROM strategy_runs r
                   JOIN strategy_signals s ON s.run_id = r.run_id
                   WHERE r.strategy_id = 'limit-up-ambush'
                     AND r.mode = 'live'
                     AND r.capture_origin = 'scheduled'
                     AND NOT EXISTS (
                         SELECT 1 FROM alert_event_points p
                         WHERE p.strategy_id = r.strategy_id
                           AND p.alert_date = substr(r.observed_at, 1, 10)
                           AND p.code = s.code
                           AND p.observed_at = r.observed_at
                     )
                   ORDER BY r.observed_at"""
            ).fetchall()
        for row in rows:
            run = self.get_run(row["run_id"])
            if run is not None:
                self.record_alert_run(run)

    def record_alert_run(self, run: StrategyRun) -> None:
        """Merge one scheduled scan into per-stock alert events."""
        alert_date = run.observed_at.date().isoformat()
        observed_at = run.observed_at.isoformat()
        with self._connect() as conn:
            for signal in run.signals:
                snapshot = signal.snapshot
                count_semantics = (
                    "strengthening"
                    if any(factor.key == "price_momentum" for factor in signal.factors)
                    else "matches"
                )
                conn.execute(
                    """INSERT INTO alert_events (
                           strategy_id, alert_date, code, name,
                           first_alert_at, last_alert_at, first_alert_price, first_alert_pct,
                           last_observed_at, latest_price, latest_pct, hit_count, max_score,
                           max_price, max_pct, min_price, min_pct, status, count_semantics
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, 'watching', ?)
                       ON CONFLICT(strategy_id, alert_date, code) DO UPDATE SET
                           name = excluded.name,
                           last_alert_at = excluded.last_alert_at,
                           last_observed_at = excluded.last_observed_at,
                           latest_price = excluded.latest_price,
                           latest_pct = excluded.latest_pct,
                           hit_count = alert_events.hit_count + 1,
                           max_score = MAX(alert_events.max_score, excluded.max_score),
                           max_price = MAX(alert_events.max_price, excluded.max_price),
                           max_pct = MAX(alert_events.max_pct, excluded.max_pct),
                           min_price = MIN(alert_events.min_price, excluded.min_price),
                           min_pct = MIN(alert_events.min_pct, excluded.min_pct),
                           count_semantics = CASE
                               WHEN alert_events.count_semantics = excluded.count_semantics
                                   THEN alert_events.count_semantics
                               ELSE 'mixed'
                           END""",
                    (
                        run.strategy_id, alert_date, signal.code, signal.name,
                        observed_at, observed_at, snapshot.price, snapshot.pct_change,
                        observed_at, snapshot.price, snapshot.pct_change, signal.score,
                        snapshot.price, snapshot.pct_change, snapshot.price, snapshot.pct_change,
                        count_semantics,
                    ),
                )
                conn.execute(
                    """INSERT INTO alert_event_points
                           (strategy_id, alert_date, code, observed_at, price, pct_change, score, is_alert)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                       ON CONFLICT(strategy_id, alert_date, code, observed_at) DO UPDATE SET
                           price = excluded.price,
                           pct_change = excluded.pct_change,
                           score = MAX(alert_event_points.score, excluded.score),
                           is_alert = 1""",
                    (
                        run.strategy_id, alert_date, signal.code, observed_at,
                        snapshot.price, snapshot.pct_change, signal.score,
                    ),
                )

    @staticmethod
    def _limit_up_threshold_pct(code: str) -> float:
        """Approximate exchange limit from the public quote percentage."""
        return 19.8 if code.startswith(("300", "301", "688", "689")) else 9.8

    def update_alert_outcomes(
        self,
        strategy_id: str,
        observed_at,
        snapshots: list[MarketSnapshot],
        *,
        finalize: bool = False,
    ) -> int:
        """Append quotes only for stocks that already emitted an alert today."""
        alert_date = observed_at.date().isoformat()
        observed_iso = observed_at.isoformat()
        snapshots_by_code = {snapshot.code: snapshot for snapshot in snapshots}
        updated = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM alert_events WHERE strategy_id = ? AND alert_date = ?",
                (strategy_id, alert_date),
            ).fetchall()
            for row in rows:
                snapshot = snapshots_by_code.get(row["code"])
                if snapshot is None:
                    continue
                hit_limit_now = snapshot.pct_change >= self._limit_up_threshold_pct(row["code"])
                first_limit_at = row["first_limit_up_at"] or (observed_iso if hit_limit_now else None)
                status = "hit_limit" if first_limit_at else ("not_hit" if finalize else "watching")
                conn.execute(
                    """UPDATE alert_events SET
                           name = ?, last_observed_at = ?, latest_price = ?, latest_pct = ?,
                           max_price = MAX(max_price, ?), max_pct = MAX(max_pct, ?),
                           min_price = MIN(min_price, ?), min_pct = MIN(min_pct, ?),
                           first_limit_up_at = ?, status = ?
                       WHERE strategy_id = ? AND alert_date = ? AND code = ?""",
                    (
                        snapshot.name, observed_iso, snapshot.price, snapshot.pct_change,
                        snapshot.price, snapshot.pct_change, snapshot.price, snapshot.pct_change,
                        first_limit_at, status, strategy_id, alert_date, row["code"],
                    ),
                )
                conn.execute(
                    """INSERT INTO alert_event_points
                           (strategy_id, alert_date, code, observed_at, price, pct_change, score, is_alert)
                       VALUES (?, ?, ?, ?, ?, ?, NULL, 0)
                       ON CONFLICT(strategy_id, alert_date, code, observed_at) DO UPDATE SET
                           price = excluded.price, pct_change = excluded.pct_change""",
                    (
                        strategy_id, alert_date, row["code"], observed_iso,
                        snapshot.price, snapshot.pct_change,
                    ),
                )
                updated += 1
        return updated

    def has_alert_events(self, strategy_id: str, alert_date: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM alert_events
                   WHERE strategy_id = ? AND alert_date = ? LIMIT 1""",
                (strategy_id, alert_date),
            ).fetchone()
        return row is not None

    def alert_history(
        self,
        strategy_id: str,
        *,
        alert_date: str | None = None,
        result: str | None = None,
        persistent_only: bool = False,
    ) -> dict:
        """Return a summary-first view of deduplicated alert events."""
        with self._connect() as conn:
            available_dates = [
                row["alert_date"] for row in conn.execute(
                    """SELECT DISTINCT alert_date FROM alert_events
                       WHERE strategy_id = ? ORDER BY alert_date DESC""",
                    (strategy_id,),
                ).fetchall()
            ]
            if alert_date is None:
                alert_date = available_dates[0] if available_dates else None
            if alert_date is None:
                return {
                    "strategy_id": strategy_id, "alert_date": None, "scan_count": 0,
                    "unique_stock_count": 0, "persistent_count": 0,
                    "hit_limit_count": 0, "hit_limit_rate": 0.0,
                    "count_semantics": "matches",
                    "available_dates": available_dates, "events": [],
                }
            scan_row = conn.execute(
                """SELECT COUNT(*) AS scan_count FROM strategy_runs
                   WHERE strategy_id = ? AND capture_origin = 'scheduled'
                     AND substr(observed_at, 1, 10) = ?""",
                (strategy_id, alert_date),
            ).fetchone()
            all_rows = conn.execute(
                """SELECT * FROM alert_events
                   WHERE strategy_id = ? AND alert_date = ?
                   ORDER BY hit_count DESC, max_score DESC, first_alert_at""",
                (strategy_id, alert_date),
            ).fetchall()
            rows = [
                row for row in all_rows
                if (result is None or row["status"] == result)
                and (not persistent_only or row["hit_count"] >= 3)
            ]
            events = []
            for row in rows:
                event = dict(row)
                first_price = event["first_alert_price"]
                event["max_gain_from_alert_pct"] = round(
                    (event["max_price"] / first_price - 1) * 100, 2
                )
                event["max_drawdown_from_alert_pct"] = round(
                    (event["min_price"] / first_price - 1) * 100, 2
                )
                points = conn.execute(
                    """SELECT observed_at, price, pct_change, score, is_alert
                       FROM alert_event_points
                       WHERE strategy_id = ? AND alert_date = ? AND code = ?
                       ORDER BY observed_at""",
                    (strategy_id, alert_date, row["code"]),
                ).fetchall()
                event["timeline"] = [
                    {**dict(point), "is_alert": bool(point["is_alert"])} for point in points
                ]
                events.append(event)
        unique_count = len(all_rows)
        hit_limit_count = sum(row["status"] == "hit_limit" for row in all_rows)
        semantics = {row["count_semantics"] for row in all_rows}
        count_semantics = next(iter(semantics)) if len(semantics) == 1 else "mixed"
        return {
            "strategy_id": strategy_id,
            "alert_date": alert_date,
            "scan_count": scan_row["scan_count"],
            "unique_stock_count": unique_count,
            "persistent_count": sum(row["hit_count"] >= 3 for row in all_rows),
            "count_semantics": count_semantics if semantics else "matches",
            "hit_limit_count": hit_limit_count,
            "hit_limit_rate": round(hit_limit_count / unique_count * 100, 1) if unique_count else 0.0,
            "available_dates": available_dates,
            "filtered_count": len(events),
            "events": events,
        }

    def save_run(self, run: StrategyRun, snapshots: list[MarketSnapshot] | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO strategy_runs
                   (run_id, strategy_id, version, observed_at, mode, capture_origin, universe_size, created_at, data_source, execution_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.run_id, run.strategy_id, run.version, run.observed_at.isoformat(), run.mode,
                 run.capture_origin, run.universe_size, run.observed_at.isoformat(), run.data_source, run.execution_status),
            )
            for rank, signal in enumerate(run.signals, 1):
                conn.execute(
                    "INSERT INTO strategy_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (run.run_id, rank, signal.code, signal.name, signal.score, int(signal.eligible),
                     signal.risk_level, signal.model_dump_json()),
                )
            if snapshots:
                # Re-validate to coerce NaN/missing numerics (volume_ratio etc.) to 0.0
                # before writing to NOT NULL columns. field_validator runs on parse, but a
                # caller that builds MarketSnapshot(...) directly can bypass it.
                cleaned: list[tuple] = []
                for snapshot in snapshots:
                    safe = MarketSnapshot.model_validate(snapshot.model_dump())
                    cleaned.append((
                        run.run_id, safe.code, safe.name, safe.price,
                        safe.pct_change, safe.day_low, safe.turnover_rate,
                        safe.volume_ratio, safe.market_pct_change,
                        safe.captured_at.isoformat(),
                    ))
                conn.executemany(
                    """INSERT INTO market_snapshots
                       (run_id, code, name, price, pct_change, day_low, turnover_rate, volume_ratio, market_pct_change, captured_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    cleaned,
                )

    def latest_run(self, strategy_id: str) -> StrategyRun | None:
        return self._latest_run(strategy_id)

    def latest_live_run(self, strategy_id: str) -> StrategyRun | None:
        return self._latest_run(strategy_id, mode="live")

    def latest_scheduled_run(self, strategy_id: str) -> StrategyRun | None:
        return self._latest_run(strategy_id, mode="live", capture_origin="scheduled")

    def _latest_run(
        self,
        strategy_id: str,
        *,
        mode: str | None = None,
        capture_origin: str | None = None,
    ) -> StrategyRun | None:
        with self._connect() as conn:
            where = ["strategy_id = ?"]
            params: list[str] = [strategy_id]
            if mode is not None:
                where.append("mode = ?")
                params.append(mode)
            if capture_origin is not None:
                where.append("capture_origin = ?")
                params.append(capture_origin)
            row = conn.execute(
                f"SELECT * FROM strategy_runs WHERE {' AND '.join(where)} ORDER BY observed_at DESC LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                return None
            signals = [
                Signal.model_validate_json(signal["payload_json"])
                for signal in conn.execute(
                    "SELECT payload_json FROM strategy_signals WHERE run_id = ? ORDER BY rank", (row["run_id"],)
                )
            ]
        return StrategyRun(
            run_id=row["run_id"], strategy_id=row["strategy_id"], version=row["version"],
            observed_at=row["observed_at"], mode=row["mode"], capture_origin=row["capture_origin"], data_source=row["data_source"],
            execution_status=row["execution_status"], universe_size=row["universe_size"], signals=signals,
        )

    def get_run(self, run_id: str) -> StrategyRun | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM strategy_runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            signals = [
                Signal.model_validate_json(signal["payload_json"])
                for signal in conn.execute(
                    "SELECT payload_json FROM strategy_signals WHERE run_id = ? ORDER BY rank", (run_id,)
                )
            ]
        return StrategyRun(
            run_id=row["run_id"], strategy_id=row["strategy_id"], version=row["version"],
            observed_at=row["observed_at"], mode=row["mode"], capture_origin=row["capture_origin"], data_source=row["data_source"],
            execution_status=row["execution_status"], universe_size=row["universe_size"], signals=signals,
        )

    def list_runs(
        self,
        strategy_id: str,
        *,
        limit: int = 30,
        date_from: str | None = None,
        date_to: str | None = None,
        mode: str | None = "live",
        capture_origin: str | None = "scheduled",
    ) -> list[dict]:
        """按 observed_at 倒序列出历史 run 元数据 + 候选数。

        ``date_from`` / ``date_to`` 仅取日期部分（YYYY-MM-DD），与 ``observed_at`` 前缀比对。
        默认只列 live 模式，避免历史样本数据混入前端。
        """
        where = ["strategy_id = ?"]
        params: list = [strategy_id]
        if mode is not None:
            where.append("mode = ?")
            params.append(mode)
        if capture_origin is not None:
            where.append("capture_origin = ?")
            params.append(capture_origin)
        where.append("execution_status != ?")
        params.append("sample")
        if date_from:
            where.append("substr(observed_at, 1, 10) >= ?")
            params.append(date_from)
        if date_to:
            where.append("substr(observed_at, 1, 10) <= ?")
            params.append(date_to)
        sql = (
            "SELECT r.run_id, r.strategy_id, r.version, r.observed_at, r.mode, r.capture_origin, "
            "       r.universe_size, r.data_source, r.execution_status, "
            "       COUNT(s.code) AS signal_count "
            "FROM strategy_runs r LEFT JOIN strategy_signals s ON s.run_id = r.run_id "
            f"WHERE {' AND '.join(where)} "
            "GROUP BY r.run_id "
            "ORDER BY r.observed_at DESC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def list_recent_runs_all_strategies(
        self,
        *,
        limit: int = 50,
        date_from: str | None = None,
        date_to: str | None = None,
        mode: str | None = "live",
        capture_origin: str | None = "scheduled",
    ) -> list[dict]:
        """跨策略列历史 run，用于前端"今日各策略汇总"。"""
        where = ["1=1"]
        params: list = []
        if mode is not None:
            where.append("r.mode = ?")
            params.append(mode)
        if capture_origin is not None:
            where.append("r.capture_origin = ?")
            params.append(capture_origin)
        where.append("r.execution_status != ?")
        params.append("sample")
        if date_from:
            where.append("substr(r.observed_at, 1, 10) >= ?")
            params.append(date_from)
        if date_to:
            where.append("substr(r.observed_at, 1, 10) <= ?")
            params.append(date_to)
        sql = (
            "SELECT r.run_id, r.strategy_id, r.version, r.observed_at, r.mode, r.capture_origin, "
            "       r.universe_size, r.data_source, r.execution_status, "
            "       COUNT(s.code) AS signal_count "
            "FROM strategy_runs r LEFT JOIN strategy_signals s ON s.run_id = r.run_id "
            f"WHERE {' AND '.join(where)} "
            "GROUP BY r.run_id "
            "ORDER BY r.observed_at DESC LIMIT ?"
        )
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def snapshots_for_run(self, run_id: str) -> list[MarketSnapshot]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_snapshots WHERE run_id = ? ORDER BY code", (run_id,)
            ).fetchall()
        return [
            MarketSnapshot(
                code=row["code"], name=row["name"], price=row["price"],
                pct_change=row["pct_change"], day_low=row["day_low"],
                turnover_rate=row["turnover_rate"], volume_ratio=row["volume_ratio"],
                market_pct_change=row["market_pct_change"], captured_at=row["captured_at"],
            )
            for row in rows
        ]

    def pending_t1_signals(self, before_date: str) -> list[tuple[str, Signal]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT s.run_id, s.payload_json
                   FROM strategy_runs r
                   JOIN strategy_signals s ON s.run_id = r.run_id
                   LEFT JOIN t1_outcomes o ON o.run_id = s.run_id AND o.code = s.code
                    WHERE r.execution_status = 'tradable'
                      AND r.capture_origin = 'scheduled'
                     AND substr(r.observed_at, 1, 10) < ?
                     AND o.run_id IS NULL
                   ORDER BY r.observed_at, s.rank""",
                (before_date,),
            ).fetchall()
        return [(row["run_id"], Signal.model_validate_json(row["payload_json"])) for row in rows]

    def save_t1_outcome(self, run_id: str, outcome_date: str, trade: PaperTrade) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO t1_outcomes (run_id, code, outcome_date, payload_json) VALUES (?, ?, ?, ?)",
                (run_id, trade.code, outcome_date, trade.model_dump_json()),
            )

    def recent_t1_outcomes(self, limit: int = 100) -> list[PaperTrade]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM t1_outcomes ORDER BY outcome_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [PaperTrade.model_validate_json(row["payload_json"]) for row in rows]

    def t1_outcomes_due_for_review(self, outcome_date: str) -> list[tuple[str, Signal, PaperTrade]]:
        """Completed formal T+1 outcomes for today's observational chart snapshot."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT o.run_id, s.payload_json AS signal_json, o.payload_json AS trade_json
                   FROM t1_outcomes o
                   JOIN strategy_runs r ON r.run_id = o.run_id
                   JOIN strategy_signals s ON s.run_id = o.run_id AND s.code = o.code
                   WHERE o.outcome_date = ?
                     AND r.mode = 'live'
                     AND r.capture_origin = 'scheduled'
                     AND r.execution_status = 'tradable'
                   ORDER BY r.observed_at, s.rank""",
                (outcome_date,),
            ).fetchall()
        return [
            (
                row["run_id"],
                Signal.model_validate_json(row["signal_json"]),
                PaperTrade.model_validate_json(row["trade_json"]),
            )
            for row in rows
        ]

    def latest_t1_reviews(self, strategy_id: str) -> tuple[str | None, list[dict]]:
        """Return the latest completed T+1 review day for formal strategy runs."""
        conditions = """r.strategy_id = ?
                        AND r.mode = 'live'
                        AND r.capture_origin = 'scheduled'
                        AND r.execution_status = 'tradable'"""
        with self._connect() as conn:
            latest_row = conn.execute(
                f"""SELECT MAX(o.outcome_date) AS review_date
                    FROM t1_outcomes o
                    JOIN strategy_runs r ON r.run_id = o.run_id
                    WHERE {conditions}""",
                (strategy_id,),
            ).fetchone()
            review_date = latest_row["review_date"]
            if review_date is None:
                return None, []
            rows = conn.execute(
                f"""SELECT r.observed_at, o.payload_json
                    FROM t1_outcomes o
                    JOIN strategy_runs r ON r.run_id = o.run_id
                    WHERE {conditions} AND o.outcome_date = ?
                    ORDER BY r.observed_at DESC, o.code""",
                (strategy_id, review_date),
            ).fetchall()
        return review_date, [
            {
                "recommendation_at": row["observed_at"],
                "trade": PaperTrade.model_validate_json(row["payload_json"]),
            }
            for row in rows
        ]
