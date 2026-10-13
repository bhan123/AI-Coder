"""Read-only production audit. Run with DB path; excludes 2026-09-07 intraday results."""
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


def summary(rows):
    returns = [(r['latest_price'] / r['first_alert_price'] - 1) * 100 for r in rows]
    return {
        'n': len(rows),
        'observed_limit_hits': sum(r['status'] == 'hit_limit' for r in rows),
        'positive_last_observation': sum(x > 0 for x in returns),
        'mean_return_pct': round(statistics.mean(returns), 3) if returns else None,
        'median_return_pct': round(statistics.median(returns), 3) if returns else None,
        'unfinalized': sum(r['status'] == 'watching' for r in rows),
        'last_observation_before_1457': sum(r['last_observed_at'][11:16] < '14:57' for r in rows),
        'last_observation_before_1500': sum(r['last_observed_at'][11:16] < '15:00' for r in rows),
    }


db = sqlite3.connect(Path(sys.argv[1]).resolve().as_uri() + '?mode=ro', uri=True)
db.row_factory = sqlite3.Row
db.execute('BEGIN')
report = {'scope': '2026-08-17 <= alert_date < 2026-09-07; latest observed quote is NOT official close'}
report['table_counts'] = {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in (
    'strategy_runs', 'strategy_signals', 'market_snapshots', 'alert_events', 'alert_event_points', 't1_outcomes')}
report['run_coverage'] = [dict(r) for r in db.execute('''
    SELECT strategy_id, version, COUNT(*) runs, MIN(observed_at) first_at, MAX(observed_at) last_at
    FROM strategy_runs WHERE capture_origin='scheduled' GROUP BY strategy_id, version''')]
events = list(db.execute("SELECT * FROM alert_events WHERE alert_date >= '2026-08-17' AND alert_date < '2026-09-07'"))
report['alert_totals'] = summary(events)
groups = defaultdict(list)
for row in events:
    groups[row['alert_date']].append(row)
report['alert_days'] = {day: summary(rows) for day, rows in sorted(groups.items())}
report['alert_segments'] = {key: summary(rows) for key, rows in {
    'main_board': [r for r in events if not r['code'].startswith(('3', '688', '689'))],
    '20pct_board': [r for r in events if r['code'].startswith(('3', '688', '689'))],
    'hits_ge_3': [r for r in events if r['hit_count'] >= 3],
    'hits_lt_3': [r for r in events if r['hit_count'] < 3],
    'max_score_ge_85': [r for r in events if r['max_score'] >= 85],
    'max_score_lt_85': [r for r in events if r['max_score'] < 85],
}.items()}
report['scan_days'] = [dict(r) for r in db.execute('''
    SELECT substr(observed_at,1,10) day, COUNT(*) scans, MIN(universe_size) min_universe,
           MIN(observed_at) first_scan, MAX(observed_at) last_scan
    FROM strategy_runs WHERE strategy_id='limit-up-ambush' AND capture_origin='scheduled'
    AND observed_at >= '2026-08-17' GROUP BY day ORDER BY day''')]
report['t1_coverage'] = [dict(r) for r in db.execute('''
    SELECT r.strategy_id, COUNT(*) signals, COUNT(o.code) outcomes,
           SUM(CASE WHEN o.code IS NOT NULL AND json_type(o.payload_json,'$.market_review')='object' THEN 1 ELSE 0 END) charts,
           MIN(CASE WHEN o.code IS NULL THEN r.observed_at END) oldest_pending
    FROM strategy_runs r JOIN strategy_signals s ON s.run_id=r.run_id
    LEFT JOIN t1_outcomes o ON o.run_id=s.run_id AND o.code=s.code
    WHERE r.capture_origin='scheduled' AND r.execution_status='tradable'
      AND r.observed_at >= '2026-08-17' AND r.observed_at < '2026-09-07'
    GROUP BY r.strategy_id''')]
points = defaultdict(list)
for r in db.execute("SELECT * FROM alert_event_points WHERE alert_date >= '2026-08-17' AND alert_date < '2026-09-07' ORDER BY observed_at"):
    points[(r['alert_date'], r['code'])].append(r)
interrupted = []
count_mismatches = []
for e in events:
    seq = points[(e['alert_date'], e['code'])]
    hit_indices = [i for i, p in enumerate(seq) if p['is_alert']]
    if len(hit_indices) != e['hit_count']:
        count_mismatches.append({'day':e['alert_date'], 'code':e['code'], 'hit_count':e['hit_count'], 'alert_points':len(hit_indices)})
    if e['hit_count'] >= 3 and hit_indices and any(not p['is_alert'] for p in seq[hit_indices[0]:hit_indices[-1]+1]):
        interrupted.append({'day':e['alert_date'], 'code':e['code'], 'hit_count':e['hit_count']})
report['persistent_events_with_gaps'] = {'count':len(interrupted), 'examples':interrupted[:3]}
report['count_mismatches'] = {'count':len(count_mismatches), 'examples':count_mismatches[:3]}
intervals = []
times = [datetime.fromisoformat(r[0]) for r in db.execute("SELECT observed_at FROM strategy_runs WHERE strategy_id='limit-up-ambush' AND capture_origin='scheduled' AND observed_at >= '2026-08-17' ORDER BY observed_at")]
for a,b in zip(times,times[1:]):
    if a.date()==b.date() and (a.hour<12)==(b.hour<12):
        intervals.append((b-a).total_seconds())
report['scan_intervals_seconds'] = {'n':len(intervals), 'median':round(statistics.median(intervals),1), 'max':round(max(intervals),1), 'over_300':sum(x>300 for x in intervals)} if intervals else {}
report['sqlite_settings'] = {p:db.execute(f'PRAGMA {p}').fetchone()[0] for p in ('journal_mode','foreign_keys','busy_timeout')}
db.rollback()
db.close()
print(json.dumps(report, ensure_ascii=False, indent=2))
