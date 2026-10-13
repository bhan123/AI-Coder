"""Bounded, read-only diagnostics for the independent closing collection queue."""
from contextlib import closing
from datetime import date, datetime, time
from pathlib import Path
import re
import sqlite3

from app.review_evidence import SHANGHAI


JOB_FIELDS = ('trade_date,code,provider,status,attempt_count,evidence_id,updated_at,'
              'last_error_type,next_retry_at,lease_until')
ATTEMPT_FIELDS = 'sequence,trade_date,code,provider,status,attempted_at,finished_at,evidence_id,error_type'


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError('date must use YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if not 1900 <= parsed.year <= 9998:
        raise ValueError('date outside supported range')
    return parsed


def _validate(*, date_from=None, date_to=None, code=None, status=None, limit=50, offset=0):
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or not 0 <= offset <= 1000000:
        raise ValueError('invalid pagination')
    if (date_from is None) != (date_to is None):
        raise ValueError('both dates are required')
    if date_from is not None:
        start, end = _day(date_from), _day(date_to)
        if start > end or (end - start).days > 365:
            raise ValueError('date range must be ordered and at most 366 days')
    if code is not None and (not isinstance(code, str) or not re.fullmatch(r'[0-9]{6}', code)):
        raise ValueError('invalid security code')
    if status is not None and status not in ('pending', 'running', 'failed', 'completed'):
        raise ValueError('invalid queue status')


def _aware(value):
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError('queue time requires a timezone')
    return parsed.astimezone(SHANGHAI)


def _availability(row, now):
    unknown = dict(availability='unknown', ready_to_collect=False, next_eligible_at=None)
    if row['status'] not in ('pending', 'running', 'failed', 'completed'):
        return unknown | {'diagnostic_flags': ['unknown_queue_status']}
    if row['status'] == 'completed':
        return dict(availability='completed', ready_to_collect=False, next_eligible_at=None)
    try:
        ready_at = datetime.combine(_day(row['trade_date']), time(16), SHANGHAI)
        retry_at = _aware(row['next_retry_at']) if row['next_retry_at'] else None
        lease_at = _aware(row['lease_until']) if row['status'] == 'running' else None
    except (TypeError, ValueError):
        return unknown | {'diagnostic_flags': ['invalid_queue_timestamp']}
    eligible_at = max(value for value in (ready_at, retry_at, lease_at) if value is not None)
    if now < ready_at:
        state = 'awaiting_close'
    elif lease_at and now < lease_at:
        state = 'running'
    elif retry_at and now < retry_at:
        state = 'cooldown'
    else:
        state = 'lease_expired' if row['status'] == 'running' else 'ready'
    return dict(availability=state, ready_to_collect=now >= eligible_at,
                next_eligible_at=eligible_at.isoformat())


class ClosingQueueReader:
    def __init__(self, path, *, clock=None):
        self.path = Path(path)
        self.clock = clock or (lambda: datetime.now(SHANGHAI))

    def search(self, *, date_from=None, date_to=None, code=None, status=None, limit=50, offset=0):
        _validate(date_from=date_from, date_to=date_to, code=code, status=status, limit=limit, offset=offset)
        now = _aware(self.clock().isoformat())
        conditions, params = [], []
        if date_from is not None:
            conditions.append('trade_date BETWEEN ? AND ?')
            params.extend((date_from, date_to))
        for column, value in [('code', code), ('status', status)]:
            if value is not None:
                conditions.append(f'{column}=?')
                params.append(value)
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        if not self.path.exists():
            return {'as_of': now.isoformat(), 'queue_status': 'not_initialized', 'items': [],
                    'total': 0, 'counts_by_status': {}, 'limit': limit, 'offset': offset, 'next_offset': None}
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN')
            counts = {row['status']: row['n'] for row in conn.execute(
                'SELECT status,COUNT(*) AS n FROM closing_jobs' + where + ' GROUP BY status', params)}
            rows = [dict(row) for row in conn.execute(
                'SELECT ' + JOB_FIELDS + ' FROM closing_jobs' + where +
                ' ORDER BY trade_date DESC,code,provider LIMIT ? OFFSET ?', (*params, limit, offset))]
        for row in rows:
            row.update(_availability(row, now))
        total = sum(counts.values())
        return {'as_of': now.isoformat(), 'queue_status': 'available', 'items': rows,
                'total': total, 'counts_by_status': counts, 'limit': limit, 'offset': offset,
                'next_offset': offset + len(rows) if offset + len(rows) < total else None}

    def history(self, *, trade_date, code, provider, limit=50, offset=0):
        _validate(date_from=trade_date, date_to=trade_date, code=code, limit=limit, offset=offset)
        if code is None or trade_date is None or not isinstance(provider, str) or not provider.strip() or len(provider) > 128:
            raise ValueError('exact date, code and provider are required')
        now = _aware(self.clock().isoformat())
        if not self.path.exists():
            return {'as_of': now.isoformat(), 'queue_status': 'not_initialized', 'job': None,
                    'items': [], 'total': 0, 'limit': limit, 'offset': offset, 'next_offset': None}
        key = (trade_date, code, provider)
        where = ' WHERE trade_date=? AND code=? AND provider=?'
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN')
            raw_job = conn.execute('SELECT ' + JOB_FIELDS + ' FROM closing_jobs' + where, key).fetchone()
            total = conn.execute('SELECT COUNT(*) FROM closing_attempts' + where, key).fetchone()[0]
            rows = [dict(row) for row in conn.execute(
                'SELECT ' + ATTEMPT_FIELDS + ' FROM closing_attempts' + where +
                ' ORDER BY sequence DESC LIMIT ? OFFSET ?', (*key, limit, offset))]
        job = dict(raw_job) if raw_job else None
        if job:
            job.update(_availability(job, now))
        return {'as_of': now.isoformat(), 'queue_status': 'available', 'job': job,
                'items': rows, 'total': total, 'limit': limit, 'offset': offset,
                'next_offset': offset + len(rows) if offset + len(rows) < total else None}
