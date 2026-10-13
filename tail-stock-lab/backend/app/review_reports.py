"""Append-only, content-addressed report revisions in a separate database."""
from contextlib import closing
from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from app.review_center import SHANGHAI


class ReviewReportArchive:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, report: dict, *, period: str) -> dict:
        if period not in {"daily", "weekly"}:
            raise ValueError("unsupported report period")
        if period == "daily" and report["date_from"] != report["date_to"]:
            raise ValueError("daily reports require exactly one date")
        content = {key: value for key, value in report.items() if key != "as_of"}
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, allow_nan=False)
        family = ":".join((period, report["strategy_id"], report["date_from"], report["date_to"]))
        digest = sha256(canonical.encode("utf-8")).hexdigest()
        report_id = sha256((family + ":" + digest).encode("utf-8")).hexdigest()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as conn, conn:
            conn.row_factory = sqlite3.Row
            conn.execute("""CREATE TABLE IF NOT EXISTS review_reports (
                report_id TEXT PRIMARY KEY, family TEXT NOT NULL, revision INTEGER NOT NULL,
                content_hash TEXT NOT NULL, period TEXT NOT NULL, strategy_id TEXT NOT NULL,
                date_from TEXT NOT NULL, date_to TEXT NOT NULL, created_at TEXT NOT NULL,
                status TEXT NOT NULL, event_count INTEGER NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(family, revision), UNIQUE(family, content_hash))""")
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM review_reports WHERE report_id = ?", (report_id,)).fetchone()
            if existing:
                return self._metadata(existing)
            revision = conn.execute("SELECT COALESCE(MAX(revision), 0) + 1 FROM review_reports WHERE family = ?",
                                    (family,)).fetchone()[0]
            created = datetime.now(SHANGHAI).isoformat()
            conn.execute("INSERT INTO review_reports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                report_id, family, revision, digest, period, report["strategy_id"],
                report["date_from"], report["date_to"], created, report["status"],
                report["event_count"], json.dumps(report, ensure_ascii=False, allow_nan=False),
            ))
            row = conn.execute("SELECT * FROM review_reports WHERE report_id = ?", (report_id,)).fetchone()
            return self._metadata(row)

    @staticmethod
    def _metadata(row) -> dict:
        return {key: row[key] for key in (
            "report_id", "revision", "content_hash", "period", "strategy_id",
            "date_from", "date_to", "created_at", "status", "event_count")}

    def list_reports(self, *, limit: int = 50, strategy_id: str | None = None) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("report limit must be between 1 and 200")
        if not self.path.exists():
            return []
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM review_reports WHERE (? IS NULL OR strategy_id = ?)
                   ORDER BY created_at DESC, revision DESC LIMIT ?""", (strategy_id, strategy_id, limit)).fetchall()
        return [self._metadata(row) for row in rows]

    def get(self, report_id: str) -> dict | None:
        if not self.path.exists():
            return None
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM review_reports WHERE report_id = ?", (report_id,)).fetchone()
        return {**self._metadata(row), "report": json.loads(row["payload_json"])} if row else None

    def search(self, *, date_from=None, date_to=None, strategy_id=None, period=None, latest_only=False, limit=25, offset=0) -> dict:
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 1000000:
            raise ValueError("invalid report pagination")
        if period not in {None, "daily", "weekly"} or strategy_id not in {None, "fishing-reversal", "limit-up-ambush"}:
            raise ValueError("unsupported report filter")
        if (date_from is None) != (date_to is None):
            raise ValueError("both date bounds are required")
        if date_from is not None:
            start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
            if start.isoformat() != date_from or end.isoformat() != date_to or start.year < 1900 or end.year > 9998 or start > end or (end-start).days > 365:
                raise ValueError("report dates must be ordered and at most 366 days")
        result = {"reports": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}
        if not self.path.exists():
            return result
        where = "(? IS NULL OR strategy_id=?) AND (? IS NULL OR date_to>=?) AND (? IS NULL OR date_from<=?) AND (? IS NULL OR period=?)"
        params = (strategy_id, strategy_id, date_from, date_from, date_to, date_to, period, period)
        if latest_only:
            where += " AND NOT EXISTS (SELECT 1 FROM review_reports newer WHERE newer.family=review_reports.family AND newer.revision>review_reports.revision)"
        columns = "report_id, revision, content_hash, period, strategy_id, date_from, date_to, created_at, status, event_count"
        with closing(sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            total = conn.execute(f"SELECT COUNT(*) FROM review_reports WHERE {where}", params).fetchone()[0]
            rows = conn.execute(f"SELECT {columns} FROM review_reports WHERE {where} ORDER BY created_at DESC, revision DESC, report_id DESC LIMIT ? OFFSET ?",
                                (*params, limit, offset)).fetchall()
        return {**result, "reports": [self._metadata(row) for row in rows], "total": total, "has_more": offset + len(rows) < total}
