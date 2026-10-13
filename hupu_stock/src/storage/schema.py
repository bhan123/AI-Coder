"""SQLite DDL。

设计文档 §4.1 表结构。所有表都用 metric_version / lexicon_version / board_dict_version
标记，便于指标回算和回测一致性。
"""
from __future__ import annotations


SCHEMA_STATEMENTS: list[str] = [
    # 主帖
    """
    CREATE TABLE IF NOT EXISTS threads (
        thread_id       TEXT PRIMARY KEY,
        title           TEXT,
        content         TEXT,
        replies         INTEGER DEFAULT 0,
        likes           INTEGER DEFAULT 0,
        views           INTEGER DEFAULT 0,
        author_hash     TEXT,
        post_time       TIMESTAMP NOT NULL,
        crawl_time      TIMESTAMP NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_threads_time ON threads(post_time);",
    # 回复
    """
    CREATE TABLE IF NOT EXISTS replies (
        reply_id        TEXT PRIMARY KEY,
        thread_id       TEXT NOT NULL,
        content         TEXT NOT NULL,
        likes           INTEGER DEFAULT 0,
        author_hash     TEXT,
        reply_time      TIMESTAMP NOT NULL,
        crawl_time      TIMESTAMP NOT NULL,
        FOREIGN KEY (thread_id) REFERENCES threads(thread_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_replies_thread_time ON replies(thread_id, reply_time);",
    "CREATE INDEX IF NOT EXISTS idx_replies_time ON replies(reply_time);",
    # 单条文本分析结果
    """
    CREATE TABLE IF NOT EXISTS item_analysis (
        item_id             TEXT NOT NULL,
        item_type           TEXT NOT NULL,
        board               TEXT NOT NULL,
        is_primary          INTEGER NOT NULL,
        match_weight        REAL NOT NULL,
        sentiment_score     REAL,
        matched_keywords    TEXT,
        lexicon_version     TEXT NOT NULL,
        board_dict_version  TEXT NOT NULL,
        analyzed_at         TIMESTAMP NOT NULL,
        PRIMARY KEY (item_id, item_type, board)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_item_analysis_board ON item_analysis(board);",
    # 板块 × 日期聚合指标
    """
    CREATE TABLE IF NOT EXISTS daily_metrics (
        board               TEXT NOT NULL,
        date                DATE NOT NULL,
        is_top_board        INTEGER NOT NULL DEFAULT 0,
        history_days        INTEGER,
        confidence          TEXT,
        post_count          INTEGER,
        reply_count         INTEGER,
        effective_item_count REAL,
        unique_authors      INTEGER,
        hot_raw             REAL,
        hot_score           REAL,
        sent_score          REAL,
        item_sent_std       REAL,
        consensus_score     REAL,
        heat_momentum       REAL,
        coverage_score      REAL,
        price_extension     REAL,
        crowding_score      REAL,
        state               TEXT,
        metric_version      TEXT NOT NULL,
        lexicon_version     TEXT NOT NULL,
        board_dict_version  TEXT NOT NULL,
        computed_at         TIMESTAMP,
        PRIMARY KEY (board, date)
    );
    """,
    # 每日全局质量统计
    """
    CREATE TABLE IF NOT EXISTS daily_pipeline_stats (
        date                DATE PRIMARY KEY,
        crawled_threads     INTEGER,
        crawled_replies     INTEGER,
        analyzed_items      INTEGER,
        matched_items       INTEGER,
        unmatched_items     INTEGER,
        unmatched_rate      REAL,
        top_board_count     INTEGER,
        computed_at         TIMESTAMP
    );
    """,
    # 每次分析流水线的可审计运行记录
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id              TEXT PRIMARY KEY,
        started_at          TIMESTAMP NOT NULL,
        finished_at         TIMESTAMP,
        status              TEXT NOT NULL,
        input_start         TIMESTAMP,
        input_end           TIMESTAMP,
        latest_thread_time  TIMESTAMP,
        latest_reply_time   TIMESTAMP,
        latest_price_date   DATE,
        analyzed_items      INTEGER,
        matched_items       INTEGER,
        unmatched_items     INTEGER,
        top_board_count     INTEGER,
        error_summary       TEXT
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_finished_at ON pipeline_runs(finished_at);",
    # 历史回填的线程级检查点。完成线程不在恢复执行时重复抓详情页；失败线程可重试。
    """
    CREATE TABLE IF NOT EXISTS backfill_thread_progress (
        job_key             TEXT NOT NULL,
        thread_id           TEXT NOT NULL,
        listed_activity_time TIMESTAMP,
        status              TEXT NOT NULL,
        last_completed_page INTEGER NOT NULL DEFAULT 0,
        completed_at        TIMESTAMP,
        last_error          TEXT,
        PRIMARY KEY (job_key, thread_id)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_backfill_progress_status ON backfill_thread_progress(job_key, status);",
    # 板块行情
    """
    CREATE TABLE IF NOT EXISTS sector_prices (
        board               TEXT NOT NULL,
        date                DATE NOT NULL,
        close               REAL,
        pct_change_1d       REAL,
        pct_change_5d       REAL,
        pct_change_10d      REAL,
        pct_change_20d      REAL,
        up_extension_10d    REAL,
        down_extension_10d  REAL,
        PRIMARY KEY (board, date)
    );
    """,
]


def init_db(conn) -> None:
    """对已打开的 sqlite3 连接执行所有 DDL。"""
    cur = conn.cursor()
    for stmt in SCHEMA_STATEMENTS:
        cur.execute(stmt)
    # CREATE TABLE IF NOT EXISTS 不会给已部署的数据库补列；回填检查点需要平滑升级。
    progress_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(backfill_thread_progress)").fetchall()
    }
    if "last_completed_page" not in progress_columns:
        cur.execute(
            "ALTER TABLE backfill_thread_progress "
            "ADD COLUMN last_completed_page INTEGER NOT NULL DEFAULT 0"
        )
    conn.commit()
