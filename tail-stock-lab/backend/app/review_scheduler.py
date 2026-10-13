"""Independent report worker. Calendar weekdays are not verified trading days."""
from contextlib import closing
from datetime import date, datetime, time, timedelta
from itertools import combinations
from pathlib import Path
import json
import sqlite3
from uuid import uuid4

from app.review_center import ReviewCenter, SHANGHAI
from app.review_collection import ClosingCollector
from app.review_reports import ReviewReportArchive


def due_windows(now, *, lookback_days=7):
    if now.tzinfo is None or type(lookback_days) is not int or not 1 <= lookback_days <= 31:
        raise ValueError('aware clock and lookback of 1..31 days required')
    now = now.astimezone(SHANGHAI)
    windows = []
    for offset in reversed(range(lookback_days)):
        day = now.date() - timedelta(days=offset)
        if day.weekday() < 5 and now >= datetime.combine(day, time(16, 30), SHANGHAI):
            windows.append(('daily', day.isoformat(), day.isoformat()))
        if day.weekday() == 4 and now >= datetime.combine(day, time(18), SHANGHAI):
            windows.append(('weekly', (day-timedelta(days=4)).isoformat(), day.isoformat()))
    return windows


class ReviewReportScheduler:
    def __init__(self, source_db, *, provider=None, clock=None):
        self.source = Path(source_db)
        self.state_path = self.source.parent / 'review_scheduler.db'
        self.archive_path = self.source.parent / 'review_reports.db'
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.collector = ClosingCollector(self.source, provider=provider, clock=self.clock)
        paths = (self.source, self.state_path, self.archive_path, self.collector.evidence_path, self.collector.queue_path)
        for a, b in combinations(paths, 2):
            if a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b)):
                raise ValueError('all review databases must be separate')

    def _connect(self):
        conn = sqlite3.connect(self.state_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    def _claim(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        now = self.clock().astimezone(SHANGHAI)
        token = uuid4().hex
        with closing(self._connect()) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS worker (id INTEGER PRIMARY KEY, token TEXT, lease_until TEXT, next_run TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS runs (token TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT, status TEXT, result_json TEXT)')
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM worker WHERE id=1').fetchone()
            if row and row['token'] and datetime.fromisoformat(row['lease_until']) > now:
                return None, 'running'
            if row and row['next_run'] and datetime.fromisoformat(row['next_run']) > now:
                return None, 'cooldown'
            if row and row['token']:
                conn.execute("UPDATE runs SET status='abandoned',finished_at=? WHERE token=?", (now.isoformat(), row['token']))
            conn.execute('INSERT OR REPLACE INTO worker VALUES(1,?,?,NULL)', (token, (now+timedelta(minutes=15)).isoformat()))
            conn.execute("INSERT INTO runs VALUES(?,?,NULL,'running',NULL)", (token, now.isoformat()))
        return token, 'running'

    def _owned(self, conn, token):
        row = conn.execute('SELECT * FROM worker WHERE id=1').fetchone()
        return row and row['token'] == token and datetime.fromisoformat(row['lease_until']) > self.clock()

    def _carryover_windows(self, windows):
        """Find V1 recommendations whose scheduled next session is due now.

        Search at most 31 days before the normal window: this covers every
        closure in the supported 2026 schedule, not unlimited offline recovery.
        Only actual formal V1 events create additional report families.
        """
        start, end = min(w[1] for w in windows), max(w[2] for w in windows)
        boundary = date.fromisoformat(start)
        report = ReviewCenter(self.source).report('fishing-reversal',
            (boundary-timedelta(days=31)).isoformat(),
            (boundary-timedelta(days=1)).isoformat(), as_of=self.clock())
        extra = set()
        for event in report['events']:
            calendar = event['next_day_close']['calendar']
            if calendar['status'] != 'scheduled' or not start <= calendar['next_date'] <= end:
                continue
            day = date.fromisoformat(event['date'])
            extra.add(('daily', day.isoformat(), day.isoformat()))
            monday = day-timedelta(days=day.weekday())
            friday = monday+timedelta(days=4)
            if self.clock() >= datetime.combine(friday, time(18), SHANGHAI):
                extra.add(('weekly', monday.isoformat(), friday.isoformat()))
        return sorted(extra-set(windows))

    def tick(self, *, lookback_days=7, max_jobs=50):
        windows = due_windows(self.clock(), lookback_days=lookback_days)
        if type(max_jobs) is not int or not 1 <= max_jobs <= 500:
            raise ValueError('max_jobs must be 1..500')
        if not windows:
            return {'status':'not_due', 'reports':[]}
        token, status = self._claim()
        if token is None:
            return {'status':status, 'reports':[]}
        result = {'status':'completed', 'reports':[], 'errors':[], 'calendar_verified':False}
        try:
            plan = [(period, strategy, start, end) for period, start, end in windows
                    for strategy in ('fishing-reversal', 'limit-up-ambush')]
            try:
                carryover = self._carryover_windows(windows)
                plan.extend((period, 'fishing-reversal', start, end) for period, start, end in carryover)
                result['v1_carryover_windows'] = carryover
            except Exception as exc:
                result['errors'].append({'stage':'next_session_carryover','type':type(exc).__name__})
                result['status'] = 'partial'
            try:
                result['collection'] = self.collector.run(min(w[2] for w in plan), max(w[3] for w in plan), max_jobs=max_jobs)
                if any(result['collection'][k] for k in ('failed','deferred','lease_lost')):
                    result['status'] = 'partial'
            except Exception as exc:
                # Store only exception classes, never feed bodies, URLs, credentials or paths.
                result['errors'].append({'stage':'collection','type':type(exc).__name__})
                result['status'] = 'partial'
            center, archive = ReviewCenter(self.source), ReviewReportArchive(self.archive_path)
            for period, strategy, start, end in plan:
                try:
                    report = center.report(strategy, start, end, as_of=self.clock())
                    # Fence archive writes as well as status writes after a lease expires.
                    with closing(self._connect()) as conn, conn:
                        conn.execute('BEGIN IMMEDIATE')
                        if not self._owned(conn, token):
                            return {**result, 'status':'lease_lost'}
                        result['reports'].append(archive.save(report, period=period))
                except Exception as exc:
                    result['errors'].append({'stage':'report','strategy_id':strategy,'period':period,'date_from':start,'date_to':end,'type':type(exc).__name__})
                    result['status'] = 'partial'
            if result['errors'] and not result['reports']:
                result['status'] = 'failed'
        except BaseException:
            result['status'] = 'interrupted'
            raise
        finally:
            with closing(self._connect()) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                if self._owned(conn, token):
                    now = self.clock().astimezone(SHANGHAI)
                    conn.execute('UPDATE runs SET finished_at=?,status=?,result_json=? WHERE token=?',
                                 (now.isoformat(), result['status'], json.dumps(result, ensure_ascii=False), token))
                    conn.execute('UPDATE worker SET token=NULL,lease_until=NULL,next_run=? WHERE id=1', ((now+timedelta(minutes=15)).isoformat(),))
        return result

    def status(self):
        return scheduler_status(self.state_path, now=self.clock())


def scheduler_status(path, *, now=None):
    path = Path(path)
    now = now or datetime.now(SHANGHAI)
    result = {'timezone':'Asia/Shanghai', 'daily_at':'16:30', 'weekly_at':'Friday 18:00',
              'calendar_verified':False, 'timer_enabled':None, 'last_run':None, 'recent_runs':[],
              'note':'工作日排期，非已核验交易日历；运行记录不能证明服务器定时器已启用。'}
    if not path.exists():
        return result
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT * FROM runs ORDER BY started_at DESC,rowid DESC LIMIT 10').fetchall()
        worker = conn.execute('SELECT * FROM worker WHERE id=1').fetchone()
    for row in rows:
        item = {k:row[k] for k in ('started_at','finished_at','status')}
        item['result'] = json.loads(row['result_json']) if row['result_json'] else None
        if item['status'] == 'running' and worker and worker['token'] == row['token'] and datetime.fromisoformat(worker['lease_until']) <= now:
            item['status'] = 'lease_expired'
        result['recent_runs'].append(item)
    result['last_run'] = result['recent_runs'][0] if rows else None
    return result
