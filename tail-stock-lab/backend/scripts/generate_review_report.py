"""Generate evidence snapshots; scheduling/close reconciliation are separate.

Example: python scripts/generate_review_report.py --date-from 2026-09-04
         --date-to 2026-09-04 --period daily
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.review_center import ReviewCenter
from app.review_reports import ReviewReportArchive


def generate_reports(source_db, archive_db, *, period, date_from, date_to):
    source, archive = Path(source_db).resolve(), Path(archive_db).resolve()
    if source == archive or (archive.exists() and source.exists() and source.samefile(archive)):
        raise ValueError("report archive must be separate from source database")
    center, store = ReviewCenter(source), ReviewReportArchive(archive)
    # Validate/read both strategies before writing any artifact.
    reports = [center.report(strategy_id, date_from, date_to)
               for strategy_id in ("fishing-reversal", "limit-up-ambush")]
    return [store.save(report, period=period) for report in reports]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default="data/tail_stock_lab.db")
    parser.add_argument("--archive-db", default="data/review_reports.db")
    parser.add_argument("--period", choices=("daily", "weekly"), required=True)
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    args = parser.parse_args()
    reports = generate_reports(args.source_db, args.archive_db, period=args.period,
                               date_from=args.date_from, date_to=args.date_to)
    print(json.dumps({"reports": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
