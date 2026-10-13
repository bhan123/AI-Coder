from pathlib import Path

from engine.db import ContentStore
from engine.metrics import import_metrics_csv, weekly_summary


def test_import_metrics_csv_and_summarize(tmp_path: Path):
    store = ContentStore(tmp_path / "content.sqlite3")
    store.initialize()
    csv_path = tmp_path / "metrics.csv"
    csv_path.write_text(
        "dedupe_key,platform,metric_date,views,likes,collects,comments,shares,follows,notes\n"
        "github:owner/repo,wechat,2026-06-30,1000,50,30,10,8,12,good\n"
        "github:owner/repo,zhihu,2026-06-30,500,20,15,6,5,4,ok\n",
        encoding="utf-8",
    )

    imported = import_metrics_csv(store, csv_path)
    summary = weekly_summary(store, since_date="2026-06-24")

    assert imported == 2
    assert summary["total_views"] == 1500
    assert summary["total_follows"] == 16
    assert summary["platforms"]["wechat"]["views"] == 1000
