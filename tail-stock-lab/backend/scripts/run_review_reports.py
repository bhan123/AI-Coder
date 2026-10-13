"""One independent auto-report tick; --plan prints due windows without I/O."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.review_scheduler import ReviewReportScheduler, due_windows, SHANGHAI


def main(argv=None, *, clock=None, provider=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', default='data/tail_stock_lab.db')
    parser.add_argument('--lookback-days', type=int, default=7)
    parser.add_argument('--max-jobs', type=int, default=50)
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args(argv)
    clock = clock or (lambda:datetime.now(SHANGHAI))
    try:
        if args.plan:
            result = {'windows':due_windows(clock(),lookback_days=args.lookback_days), 'calendar_verified':False}
        else:
            result = ReviewReportScheduler(args.source_db, clock=clock, provider=provider).tick(
                lookback_days=args.lookback_days, max_jobs=args.max_jobs)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get('status') in ('failed','partial','lease_lost') else 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    # Bound the in-container process, not only its docker-exec client.
    if hasattr(signal, 'SIGALRM'):
        signal.alarm(540)
    raise SystemExit(main())
