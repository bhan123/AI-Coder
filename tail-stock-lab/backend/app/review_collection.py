"""Closing collection isolated from strategy scans and their source database."""
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path
from itertools import combinations
import sqlite3
from uuid import uuid4

import requests

from app.review_center import ReviewCenter
from app.review_closing_provider import TencentClosingProvider
from app.review_evidence import ClosingEvidence, SHANGHAI
from app.review_evidence_store import ClosingEvidenceStore


class EvidenceTargetMismatch(ValueError):
    """A provider returned evidence for a different claimed job."""


class MissingClosingEvidence(ValueError):
    """The provider returned no closing evidence."""


class InvalidClosingEvidence(ValueError):
    """The provider did not return the required evidence contract."""


class ClosingCollector:
    def __init__(self, source_db, *, evidence_db=None, queue_db=None, provider=None, clock=None):
        self.source = Path(source_db)
        self.evidence_path = Path(evidence_db or self.source.parent / "review_evidence.db")
        self.queue_path = Path(queue_db or self.source.parent / "review_collection.db")
        for left, right in combinations((self.source, self.evidence_path, self.queue_path), 2):
            if left.resolve() == right.resolve() or (left.exists() and right.exists() and left.samefile(right)):
                raise ValueError("source, evidence and collection databases must be separate")
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.provider = provider or TencentClosingProvider(clock=self.clock)
        self.evidence = ClosingEvidenceStore(self.evidence_path, clock=self.clock)

    def _connect(self):
        conn = sqlite3.connect(self.queue_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def run(self, date_from: str, date_to: str, *, max_jobs: int = 50, recheck_completed: bool = False) -> dict:
        if type(recheck_completed) is not bool:
            raise ValueError('recheck_completed must be an explicit boolean')
        if type(max_jobs) is not int or not 1 <= max_jobs <= 500:
            raise ValueError("max_jobs must be an integer from 1 to 500")
        if self.clock().tzinfo is None:
            raise ValueError("collection clock must include timezone")
        center = ReviewCenter(self.source, evidence_db=self.evidence_path)
        reports = [center.report(strategy, date_from, date_to, as_of=self.clock())
                   for strategy in ("fishing-reversal", "limit-up-ambush")]
        targets = {(event["date"], event["code"]) for report in reports for event in report["events"]}
        today = self.clock().astimezone(SHANGHAI).date().isoformat()
        for report in reports:
            for event in report['events']:
                calendar = event.get('next_day_close', {}).get('calendar', {})
                if calendar.get('status') == 'scheduled' and calendar['next_date'] <= today:
                    targets.add((calendar['next_date'], event['code']))
        targets = sorted(targets)
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS closing_jobs (
                trade_date TEXT NOT NULL, code TEXT NOT NULL, provider TEXT NOT NULL,
                status TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
                evidence_id TEXT, updated_at TEXT NOT NULL, last_error_type TEXT, next_retry_at TEXT,
                lease_token TEXT, lease_until TEXT,
                PRIMARY KEY(trade_date, code, provider))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS closing_attempts (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL, code TEXT NOT NULL, provider TEXT NOT NULL,
                status TEXT NOT NULL, attempted_at TEXT NOT NULL, evidence_id TEXT, error_type TEXT,
                attempt_id TEXT UNIQUE, finished_at TEXT)""")
            for day, code in targets:
                conn.execute("INSERT OR IGNORE INTO closing_jobs(trade_date,code,provider,status,updated_at) VALUES(?,?,?,'pending',?)",
                             (day, code, self.provider.source_name, self.clock().isoformat()))
        result = {"discovered": len(targets), "attempted": 0, "completed": 0, "failed": 0, "deferred": 0, "lease_lost": 0}
        if recheck_completed:
            # Bounded repeated runs must progress beyond the first page. Pending
            # work wins, then the least recently checked completed evidence.
            states = {(row['trade_date'], row['code']): row for row in self.jobs()
                      if row['provider'] == self.provider.source_name}
            targets.sort(key=lambda target: (
                states[target]['status'] == 'completed',
                datetime.fromisoformat(states[target]['updated_at']),
                states[target]['attempt_count'], target))
        for day, code in targets:
            key = (day, code, self.provider.source_name)
            with closing(self._connect()) as conn:
                row = conn.execute("SELECT * FROM closing_jobs WHERE trade_date=? AND code=? AND provider=?", key).fetchone()
            if row["status"] == "completed" and not recheck_completed:
                continue
            if (result["attempted"] >= max_jobs
                    or self.clock() < datetime.combine(date.fromisoformat(day), time(16), SHANGHAI)
                    or (row["next_retry_at"] and datetime.fromisoformat(row["next_retry_at"]) > self.clock())):
                result["deferred"] += 1
                continue
            token = self._claim(key, recheck_attempt_count=row['attempt_count'] if recheck_completed else None)
            if token is None:
                result["deferred"] += 1
                continue
            result["attempted"] += 1
            quote, error_type = None, None
            try:
                quote = self.provider.fetch(code, date.fromisoformat(day))
            except (requests.RequestException, ValueError) as exc:
                error_type = type(exc).__name__
            now = self.clock()
            with closing(self._connect()) as conn, conn:
                conn.execute("BEGIN IMMEDIATE")
                owned = conn.execute("SELECT lease_token FROM closing_jobs WHERE trade_date=? AND code=? AND provider=?", key).fetchone()
                if owned["lease_token"] != token:
                    result["lease_lost"] += 1
                    continue
                evidence_id = None
                try:
                    if error_type is None:
                        if quote is None:
                            raise MissingClosingEvidence('provider returned no evidence')
                        if not isinstance(quote, ClosingEvidence):
                            raise InvalidClosingEvidence('provider must return ClosingEvidence')
                        quote = ClosingEvidence.model_validate(quote.model_dump())
                        if (quote.code, quote.trade_date.isoformat(), quote.source) != (code, day, key[2]):
                            raise EvidenceTargetMismatch('evidence must match claimed security, date and provider')
                        evidence_id = self.evidence.record(quote)
                except ValueError as exc:
                    error_type = type(exc).__name__
                status = "failed" if error_type else "completed"
                retry_at = (now + timedelta(minutes=15)).isoformat() if error_type else None
                conn.execute("""UPDATE closing_jobs SET status=?,
                             evidence_id=?, updated_at=?, last_error_type=?, next_retry_at=?, lease_token=NULL, lease_until=NULL
                             WHERE trade_date=? AND code=? AND provider=?""",
                             (status, evidence_id, now.isoformat(), error_type, retry_at, *key))
                conn.execute("""UPDATE closing_attempts SET status=?, finished_at=?, evidence_id=?, error_type=?
                             WHERE attempt_id=?""", (status, now.isoformat(), evidence_id, error_type, token))
            result[status] += 1
        return result

    def _claim(self, key, *, recheck_attempt_count=None):
        now = self.clock().astimezone(SHANGHAI)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM closing_jobs WHERE trade_date=? AND code=? AND provider=?", key).fetchone()
            if (row["status"] == "completed" and row['attempt_count'] != recheck_attempt_count
                    or row["next_retry_at"] and datetime.fromisoformat(row["next_retry_at"]) > now):
                return None
            if row["status"] == "running":
                if datetime.fromisoformat(row["lease_until"]) > now:
                    return None
                conn.execute("UPDATE closing_attempts SET status='abandoned', finished_at=? WHERE attempt_id=? AND status='running'",
                             (now.isoformat(), row["lease_token"]))
            token = uuid4().hex
            conn.execute("""UPDATE closing_jobs SET status='running', attempt_count=attempt_count+1,
                         lease_token=?, lease_until=?, updated_at=? WHERE trade_date=? AND code=? AND provider=?""",
                         (token, (now + timedelta(minutes=10)).isoformat(), now.isoformat(), *key))
            conn.execute("""INSERT INTO closing_attempts(trade_date,code,provider,status,attempted_at,attempt_id)
                         VALUES(?,?,?,'running',?,?)""", (*key, now.isoformat(), token))
            return token

    def jobs(self) -> list[dict]:
        if not self.queue_path.exists():
            return []
        with closing(sqlite3.connect(self.queue_path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM closing_jobs ORDER BY trade_date,code,provider")]

    def attempts(self) -> list[dict]:
        if not self.queue_path.exists():
            return []
        with closing(sqlite3.connect(self.queue_path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("SELECT * FROM closing_attempts ORDER BY sequence")]
