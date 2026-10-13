"""SQLite 连接管理。

设计文档 §8：data/ 目录在容器内挂载为 /app/data，路径由环境变量或默认值配置。
PRAGMA 同步 = NORMAL，WAL 模式开启以兼容 FastAPI + APScheduler 并发读。
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from storage.schema import init_db

DEFAULT_DB_PATH = os.environ.get("HUPU_DB_PATH", "data/hupu.db")


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """打开 SQLite 连接，行返回 Row 类型，启用外键。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def session(db_path: str | Path = DEFAULT_DB_PATH, *, init: bool = True):
    """with session() as conn: ... 上下文管理器。

    init=True 时首次创建表结构（幂等，使用 IF NOT EXISTS）。
    """
    conn = get_connection(db_path)
    try:
        if init:
            init_db(conn)
        yield conn
    finally:
        conn.close()
