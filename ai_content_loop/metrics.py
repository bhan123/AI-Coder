from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import csv
from typing import Any

from ai_content_loop.db import ContentStore


def import_metrics_csv(store: ContentStore, csv_path: str | Path) -> int:
    with Path(csv_path).open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    normalized = []
    for row in rows:
        normalized.append(
            {
                "dedupe_key": row["dedupe_key"],
                "platform": row["platform"],
                "metric_date": row["metric_date"],
                "views": int(row["views"]),
                "likes": int(row["likes"]),
                "collects": int(row["collects"]),
                "comments": int(row["comments"]),
                "shares": int(row["shares"]),
                "follows": int(row["follows"]),
                "notes": row.get("notes", ""),
            }
        )
    return store.insert_platform_metrics(normalized)


def weekly_summary(store: ContentStore, since_date: str) -> dict[str, Any]:
    rows = store.list_metrics_since(since_date)
    platforms: dict[str, dict[str, int]] = defaultdict(
        lambda: {"views": 0, "likes": 0, "collects": 0, "comments": 0, "shares": 0, "follows": 0}
    )
    totals = {"views": 0, "likes": 0, "collects": 0, "comments": 0, "shares": 0, "follows": 0}
    for row in rows:
        platform = platforms[row["platform"]]
        for key in totals:
            value = int(row[key])
            totals[key] += value
            platform[key] += value
    return {
        "since_date": since_date,
        "total_views": totals["views"],
        "total_likes": totals["likes"],
        "total_collects": totals["collects"],
        "total_comments": totals["comments"],
        "total_shares": totals["shares"],
        "total_follows": totals["follows"],
        "platforms": dict(platforms),
    }
