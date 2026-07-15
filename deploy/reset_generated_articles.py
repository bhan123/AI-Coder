from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3


DATABASE_PATH = Path("/opt/ai-content-loop/data/ai_content_loop.sqlite3")
OUTPUT_DIR = Path("/opt/ai-content-loop/out")
DERIVED_TABLES = (
    "wechat_draft_syncs",
    "review_web_editions",
    "platform_metrics",
    "publish_queue",
    "evidence_packs",
)
PRESERVED_TABLES = ("source_items", "candidate_scores")
OUTPUT_SUBDIRS = (
    "assets",
    "drafts",
    "failures",
    "final",
    "history",
    "web",
    ".locks",
)


def table_counts(connection: sqlite3.Connection) -> dict[str, int]:
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (*PRESERVED_TABLES, *DERIVED_TABLES)
        if table in existing
    }


def clear_output_dir() -> dict[str, int]:
    output_root = OUTPUT_DIR.resolve(strict=True)
    if output_root != Path("/opt/ai-content-loop/out"):
        raise RuntimeError(f"unexpected output root: {output_root}")

    removed: dict[str, int] = {}
    for name in OUTPUT_SUBDIRS:
        target = OUTPUT_DIR / name
        target.mkdir(parents=True, exist_ok=True)
        resolved_target = target.resolve(strict=True)
        if resolved_target.parent != output_root:
            raise RuntimeError(f"unsafe output target: {resolved_target}")

        children = list(target.iterdir())
        removed[name] = len(children)
        for child in children:
            if child.is_symlink() or child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
            else:
                raise RuntimeError(f"unsupported output entry: {child}")
    return removed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear generated article data while preserving source records."
    )
    parser.add_argument(
        "--confirm",
        required=True,
        choices=("DELETE_GENERATED_ARTICLES",),
        help="Required destructive-operation confirmation.",
    )
    return parser.parse_args()


def main() -> None:
    parse_args()
    database = DATABASE_PATH.resolve(strict=True)
    if database != Path("/opt/ai-content-loop/data/ai_content_loop.sqlite3"):
        raise RuntimeError(f"unexpected database path: {database}")

    connection = sqlite3.connect(database)
    try:
        before = table_counts(connection)
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        with connection:
            for table in DERIVED_TABLES:
                if table in existing:
                    connection.execute(f"DELETE FROM {table}")
        connection.execute("VACUUM")
        after = table_counts(connection)
    finally:
        connection.close()

    removed = clear_output_dir()
    print(
        json.dumps(
            {"database_before": before, "database_after": after, "removed": removed},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
