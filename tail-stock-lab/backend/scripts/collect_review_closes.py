"""Collect missing daily close evidence without changing strategy runs.

Run from backend, then generate_review_report.py to archive revised metrics.
This command does not install a scheduler or change production services.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.review_collection import ClosingCollector


def main(argv=None, *, provider=None, clock=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default="data/tail_stock_lab.db")
    parser.add_argument("--evidence-db", help="default: review_evidence.db beside source")
    parser.add_argument("--queue-db", help="default: review_collection.db beside source")
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--recheck-completed", action="store_true",
                        help="also re-fetch completed jobs in the selected range; append changed evidence, keep history")
    args = parser.parse_args(argv)
    collector = ClosingCollector(args.source_db, evidence_db=args.evidence_db, queue_db=args.queue_db,
                                 provider=provider, clock=clock)
    result = collector.run(args.date_from, args.date_to, max_jobs=args.max_jobs,
                           recheck_completed=args.recheck_completed)
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result["failed"] or result["lease_lost"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
