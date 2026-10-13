"""FastAPI 入口。

启动时初始化 SQLite、装载词典、挂载路由；应用 lifespan 内启动 APScheduler。
静态 HTML（H5）由同一 FastAPI 服务提供，按 npm 设 /board/{name} 这样的 URL
会先匹配路由，回退到 src/web/index.html。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes import backtest, boards, history, overview
from api.db import fetch_health_status
from scheduler.jobs import configure_scheduler

WEB_DIR = Path(__file__).parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = configure_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="hupu-sector-crowding",
    description="虎扑论坛板块拥挤度预警系统",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(overview.router, tags=["overview"])
app.include_router(boards.router, prefix="/boards", tags=["boards"])
app.include_router(history.router, prefix="/boards", tags=["history"])
app.include_router(backtest.router, prefix="/backtest", tags=["backtest"])


@app.get("/health")
async def health() -> dict:
    """轻量健康检查。"""
    return fetch_health_status()


# 静态资源放最后 —— FastAPI 按注册顺序匹配；前面的路由先匹配，剩下的全部走 StaticFiles
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
