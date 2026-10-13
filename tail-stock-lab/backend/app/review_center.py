"""Read-only reconstruction of formal signals; missing outcomes remain unknown.

This reader deliberately does not instantiate StrategyRepository: reading a
report must not run migrations or historical backfills against its source.
"""
from __future__ import annotations

from contextlib import closing
from collections import Counter
from datetime import date, datetime, time, timedelta
import json
from math import isfinite
from pathlib import Path
import sqlite3
from statistics import mean, median
from zoneinfo import ZoneInfo

from app.review_evidence import ClosingEvidence, evaluate_close
from app.review_evidence_store import ClosingEvidenceStore
from app.review_analysis import explain_event, summarize_review
from app.review_t1 import read_t1_review
from app.review_next_day import next_day_close
from app.review_next_day_analysis import explain_next_day, summarize_next_day


SHANGHAI = ZoneInfo("Asia/Shanghai")
REVIEW_VERSION = "0.6.0"


def valid_price(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value > 0


def local_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=SHANGHAI) if parsed.tzinfo is None else parsed.astimezone(SHANGHAI)


def rate(values: list[bool | None]) -> dict:
    known = [value for value in values if value is not None]
    return {
        "success_count": sum(known), "eligible_count": len(known),
        "unknown_count": len(values) - len(known),
        "rate_pct": round(sum(known) / len(known) * 100, 2) if known else None,
        "coverage_pct": round(len(known) / len(values) * 100, 2) if values else None,
    }


class ReviewCenter:
    def __init__(self, source_db: str | Path, *, evidence_db: str | Path | None = None):
        self.source_db = Path(source_db)
        self.evidence = ClosingEvidenceStore(evidence_db or self.source_db.parent / "review_evidence.db")

    def report(self, strategy_id: str, date_from: str, date_to: str, *, as_of: datetime | None = None) -> dict:
        if strategy_id not in {"limit-up-ambush", "fishing-reversal"}:
            raise ValueError("unsupported review strategy")
        start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        if start.year < 1900 or end.year > 9998 or start > end or (end - start).days > 365:
            raise ValueError("review range must be ordered, within 1900..9998 and at most 366 days")
        cutoff = local_time((as_of or datetime.now(SHANGHAI)).isoformat())
        with closing(sqlite3.connect(self.source_db.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            runs = conn.execute(
                """SELECT * FROM strategy_runs WHERE strategy_id = ?
                   AND mode = 'live' AND capture_origin = 'scheduled'
                   AND execution_status = 'tradable'
                   AND substr(observed_at, 1, 10) BETWEEN ? AND ?""",
                (strategy_id, (start - timedelta(days=1)).isoformat(), (end + timedelta(days=1)).isoformat()),
            ).fetchall()
            runs = [r for r in runs if start <= local_time(r["observed_at"]).date() <= end
                    and local_time(r["observed_at"]) <= cutoff]
            events = {}
            for run in sorted(runs, key=lambda row: (local_time(row["observed_at"]), row["run_id"])):
                for row in conn.execute("SELECT * FROM strategy_signals WHERE run_id = ? AND eligible = 1",
                                        (run["run_id"],)):
                    signal = json.loads(row["payload_json"])
                    day = local_time(run["observed_at"]).date().isoformat()
                    key = (day, row["code"])
                    if key not in events:
                        events[key] = {
                            "event_id": f"{strategy_id}:{day}:{row['code']}",
                            "strategy_id": strategy_id, "date": day, "code": row["code"],
                            "name": row["name"], "first_run_id": run["run_id"],
                            "first_at": run["observed_at"], "first_price": signal["snapshot"]["price"],
                            "trigger_signal": signal, "data_source": run["data_source"],
                            "first_score": row["score"], "versions": [], "run_ids": [],
                            "quality_flags": ["close_unverified", "publication_time_unknown",
                                              "configuration_snapshot_unknown"],
                            "close_positive": None, "close_limit": None, "post_alert_limit": None,
                            "close_return_pct": None, "closing_evidence": None,
                            "last_observed_at": run["observed_at"],
                            "last_observed_price": signal["snapshot"]["price"],
                            "_price_points": [],
                        }
                    event = events[key]
                    event["run_ids"].append(run["run_id"])
                    event['_price_points'].append((run['observed_at'], signal['snapshot']['price']))
                    if run["version"] not in event["versions"]:
                        event["versions"].append(run["version"])
                    event["last_observed_at"] = run["observed_at"]
                    event["last_observed_price"] = signal["snapshot"]["price"]
            for event in events.values():
                points = conn.execute(
                    """SELECT * FROM alert_event_points WHERE strategy_id = ? AND alert_date = ? AND code = ?""",
                    (strategy_id, event["date"], event["code"]),
                ).fetchall()
                points = [p for p in points if local_time(event["first_at"]) <= local_time(p["observed_at"]) <= cutoff
                          and local_time(p["observed_at"]).date().isoformat() == event["date"]]
                if points:
                    last = max(points, key=lambda p: local_time(p["observed_at"]))
                    if local_time(last["observed_at"]) >= local_time(event["last_observed_at"]):
                        event["last_observed_at"] = last["observed_at"]
                        event["last_observed_price"] = last["price"]
                samples = event.pop('_price_points') + [(p['observed_at'], p['price']) for p in points]
                # Deduplicate matching observations; conflicting prices at one instant are not path evidence.
                grouped = {}
                session_close = datetime.combine(date.fromisoformat(event['date']), time(15), SHANGHAI)
                for observed_at, sample_price in samples:
                    # Closing evidence is separate: equal-time or later samples cannot
                    # prove a price rise happened before the selected close outcome.
                    if valid_price(sample_price) and local_time(event['first_at']) < local_time(observed_at) < session_close:
                        grouped.setdefault(local_time(observed_at), set()).add(sample_price)
                path = [(at, next(iter(prices))) for at, prices in sorted(grouped.items()) if len(prices) == 1]
                changes = [(at, round((value / event['first_price'] - 1) * 100, 4)) for at, value in path] if valid_price(event['first_price']) else []
                event['post_signal_path'] = {
                    'sample_count': len(changes), 'basis': 'stored_samples_not_continuous',
                    'max_return_pct': max(value for _, value in changes) if changes else None,
                    'min_return_pct': min(value for _, value in changes) if changes else None,
                    'first_below_at': next((at.isoformat() for at, value in changes if value < 0), None),
                }
                if len(event["versions"]) > 1:
                    event["quality_flags"].append("mixed_strategy_versions")
                event["last_observed_return_pct"] = None
                if not valid_price(event["first_price"]):
                    event["quality_flags"].append("invalid_first_price")
                elif not valid_price(event["last_observed_price"]):
                    event["quality_flags"].append("invalid_last_price")
                elif local_time(event["last_observed_at"]) <= local_time(event["first_at"]):
                    event["quality_flags"].append("no_post_alert_observation")
                else:
                    event["last_observed_return_pct"] = round(
                        (event["last_observed_price"] / event["first_price"] - 1) * 100, 4)
                change = event["last_observed_return_pct"]
                event["last_observed_positive"] = change > 0 if change is not None else None
                if strategy_id == 'fishing-reversal':
                    event['t1_review'] = read_t1_review(conn, event, cutoff)
        items = list(events.values())
        for event in items:
            closing_record = self.evidence.latest(event["code"], event["date"], as_of=cutoff)
            if closing_record is not None and closing_record.get("conflict"):
                event["quality_flags"].append("closing_source_conflict")
                event["closing_evidence"] = closing_record
                continue
            if closing_record is not None:
                outcome = evaluate_close(event, ClosingEvidence.model_validate(closing_record["quote"]))
                flags = event["quality_flags"]
                flags.remove("close_unverified")
                flags.extend(flag for flag in outcome.pop("quality_flags") if flag not in flags)
                event.update(outcome)
                event["closing_evidence"] = closing_record
        for event in items:
            if strategy_id == 'fishing-reversal':
                event['next_day_close'] = next_day_close(event, self.evidence, cutoff)
                event['next_day_analysis'] = explain_next_day(event)
            event['analysis'] = explain_event(event)
        returns = [event["last_observed_return_pct"] for event in items
                   if event["last_observed_return_pct"] is not None]
        scans_by_day = Counter(local_time(r["observed_at"]).date().isoformat() for r in runs)
        events_by_day = Counter(event["date"] for event in items)
        return {
            "calculation_version": REVIEW_VERSION, "strategy_id": strategy_id,
            "as_of": cutoff.isoformat(),
            "date_from": date_from, "date_to": date_to,
            "event_count": len(items), "scan_count": len(runs), "events": items,
            "review_summary": summarize_review(items),
            "next_day_analysis_summary": summarize_next_day(items) if strategy_id == 'fishing-reversal' else None,
            "next_day_metrics": {
                'close_positive_rate': rate([event['next_day_close']['close_positive'] for event in items]),
                'definition': '按已公布交易日历的下一交易日收盘高于首次价比例；非交易盈利率。',
            } if strategy_id == 'fishing-reversal' else None,
            "t1_summary": {
                'event_count': len(items),
                **{status: sum(event['t1_review']['status'] == status for event in items)
                   for status in ('recorded_unverified', 'missing', 'invalid_record', 'not_yet_observable')},
            } if strategy_id == 'fishing-reversal' else None,
            "coverage": {
                "calendar_verified": False,
                "dates_without_run_evidence": [
                    (start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)
                    if (start + timedelta(days=i)).isoformat() not in scans_by_day],
            },
            "status": "incomplete" if items else "zero_signals" if runs else "no_run_evidence",
            "outcomes_complete_count": sum(all(event[name] is not None for name in
                                               ("close_positive", "close_limit", "post_alert_limit")) for event in items),
            "observed_returns": {"count": len(returns), "mean_pct": round(mean(returns), 4) if returns else None,
                                 "median_pct": round(median(returns), 4) if returns else None},
            "definitions": {
                "unit": "strategy + Shanghai trading date + stock, first formal signal",
                "timestamps": "无时区的旧时间按Asia/Shanghai解释；as_of按已存观测时间截断，不代表历史发布可见性",
                "last_observed_positive_rate": "末次观测价高于首次价比例；非收盘结果、非交易胜率",
                "close_positive_rate": "正式收盘价高于首次价比例；收盘未对账为未知",
                "close_limit_rate": "正式收盘封板率；真实涨停价未核验为未知",
                "post_alert_limit_rate": "首次之后真实触板率；先后顺序或涨停价未核验为未知",
            },
            "days": [{"date": day, "scan_count": scans_by_day[day],
                      "event_count": events_by_day[day],
                      "status": "signals" if events_by_day[day] else "zero_signals"}
                     for day in sorted(scans_by_day)],
            "metrics": {
                name + "_rate": rate([event[name] for event in items])
                for name in ("close_positive", "close_limit", "post_alert_limit", "last_observed_positive")
            },
        }
