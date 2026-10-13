from __future__ import annotations

from pathlib import Path
from datetime import date as Date
from typing import Literal
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.data_provider import (
    AkshareHistoryProvider,
    AkshareIntradayProvider,
    AkshareSectorProvider,
    EastMoneySectorProvider,
    LiveSectorProvider,
    LiveSpotProvider,
    SampleHistoryProvider,
    SampleIntradayProvider,
    SampleSectorProvider,
)
from app.repository import StrategyRepository
from app.review_center import ReviewCenter
from app.review_collection_status import ClosingQueueReader
from app.review_reports import ReviewReportArchive
from app.review_scheduler import scheduler_status
from app.service import StrategyService
from app.strategies import (
    ALL_STRATEGIES,
    FishingV1Strategy,
    LeaderReconvergenceStrategy,
    PlatformBreakoutStrategy,
    SectorResonancePullbackStrategy,
    TrendPullbackStrategy,
)
from app.t1_collector import T1OutcomeCollector

repository = StrategyRepository()

STRATEGY_INSTANCES = {
    strategy_id: cls()
    for strategy_id, cls in ALL_STRATEGIES.items()
}

services: dict[str, StrategyService] = {
    strategy_id: StrategyService(
        instance,
        repository,
        history=SampleHistoryProvider(),
        intraday=SampleIntradayProvider(),
        sectors=SampleSectorProvider(),
    )
    for strategy_id, instance in STRATEGY_INSTANCES.items()
}

app = FastAPI(title="tail-stock-lab", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "strategies": [sid for sid in STRATEGY_INSTANCES],
        "default_strategy": FishingV1Strategy.strategy_id,
    }


@app.get("/api/review/summary")
def review_summary(
    strategy_id: Literal["limit-up-ambush", "fishing-reversal"],
    date_from: Date,
    date_to: Date,
) -> dict:
    """Read formal signal evidence without changing selection or source data."""
    if date_from.year < 1900 or date_to.year > 9998 or date_from > date_to or (date_to - date_from).days > 365:
        raise HTTPException(status_code=422, detail="日期范围须在1900至9998年内、有序，且不超过366天")
    try:
        return ReviewCenter(repository.db_path).report(strategy_id, date_from.isoformat(), date_to.isoformat())
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="复盘数据暂不可读取") from exc


@app.get("/api/review/automation")
def review_automation() -> dict:
    try:
        return scheduler_status(repository.db_path.parent / 'review_scheduler.db')
    except (sqlite3.Error, ValueError) as exc:
        raise HTTPException(status_code=503, detail='自动报告运行记录暂不可读取') from exc


@app.get('/api/review/collection/jobs')
def review_collection_jobs(
    date_from: Date | None = None,
    date_to: Date | None = None,
    code: str | None = Query(None, pattern=r'^[0-9]{6}$'),
    status: Literal['pending', 'running', 'failed', 'completed'] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1000000),
) -> dict:
    try:
        return ClosingQueueReader(repository.db_path.parent / 'review_collection.db').search(
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            code=code, status=status, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='补采队列查询参数无效') from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail='补采队列暂不可读取') from exc


@app.get('/api/review/collection/attempts')
def review_collection_attempts(
    trade_date: Date,
    code: str = Query(..., pattern=r'^[0-9]{6}$'),
    provider: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1000000),
) -> dict:
    try:
        return ClosingQueueReader(repository.db_path.parent / 'review_collection.db').history(
            trade_date=trade_date.isoformat(), code=code, provider=provider, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='补采尝试查询参数无效') from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail='补采尝试记录暂不可读取') from exc


@app.get("/api/review/reports")
def review_reports(
    strategy_id: Literal["limit-up-ambush", "fishing-reversal"] | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=1000000),
    date_from: Date | None = None,
    date_to: Date | None = None,
    period: Literal["daily", "weekly"] | None = None,
    latest_only: bool = False,
) -> dict:
    try:
        archive = ReviewReportArchive(repository.db_path.parent / "review_reports.db")
        return archive.search(strategy_id=strategy_id, limit=limit, offset=offset,
                              date_from=date_from.isoformat() if date_from else None,
                              date_to=date_to.isoformat() if date_to else None,
                              period=period, latest_only=latest_only)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="归档查询参数无效：请同时提供有序起止日期，范围不超过366天") from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="报告归档暂不可读取") from exc


@app.get("/api/review/reports/{report_id}")
def review_report(report_id: str) -> dict:
    try:
        item = ReviewReportArchive(repository.db_path.parent / "review_reports.db").get(report_id)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="报告归档暂不可读取") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="报告不存在")
    return item


@app.get("/api/strategies")
def list_strategies() -> dict:
    return {
        "strategies": [
            {**instance.definition(), "config": instance.current_config()}
            for instance in STRATEGY_INSTANCES.values()
        ]
    }


@app.get("/api/strategies/{strategy_id}/config")
def strategy_config(strategy_id: str) -> dict:
    instance, _ = _resolve(strategy_id)
    return {"strategy_id": strategy_id, "config": instance.current_config()}


@app.post("/api/strategies/{strategy_id}/config")
def update_strategy_config(strategy_id: str, payload: dict) -> dict:
    """用 dict 部分覆盖策略 config；非法字段忽略。"""
    instance, _ = _resolve(strategy_id)
    overrides = payload.get("overrides") if isinstance(payload, dict) else None
    new_instance = instance.with_overrides(overrides or {})
    STRATEGY_INSTANCES[strategy_id] = new_instance
    services[strategy_id] = StrategyService(
        new_instance, repository,
        history=SampleHistoryProvider(),
        intraday=SampleIntradayProvider(),
        sectors=SampleSectorProvider(),
    )
    return {"strategy_id": strategy_id, "config": new_instance.current_config()}


def _resolve(strategy_id: str) -> tuple[object, StrategyService]:
    if strategy_id not in STRATEGY_INSTANCES:
        raise HTTPException(status_code=404, detail="策略不存在")
    return STRATEGY_INSTANCES[strategy_id], services[strategy_id]


def _live_service(instance: object, *, history, intraday, sectors) -> StrategyService:
    """Create an ephemeral live service without replacing configuration state."""
    return StrategyService(
        instance,
        repository,
        history=history,
        intraday=intraday,
        sectors=sectors,
    )


@app.get("/api/strategies/{strategy_id}/latest")
def latest(strategy_id: str):
    _, _service = _resolve(strategy_id)
    return repository.latest_scheduled_run(strategy_id)


@app.get("/api/strategies/{strategy_id}/history")
def strategy_history(
    strategy_id: str,
    limit: int = Query(30, ge=1, le=200),
    date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """单个策略的历史 run 列表；按 observed_at 倒序，默认只列 live 模式。"""
    if strategy_id not in STRATEGY_INSTANCES:
        raise HTTPException(status_code=404, detail="策略不存在")
    return {"strategy_id": strategy_id, "runs": repository.list_runs(
        strategy_id, limit=limit, date_from=date_from, date_to=date_to,
    )}


@app.get("/api/strategies/{strategy_id}/alert-history")
def alert_history(
    strategy_id: str,
    date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    result: str | None = Query(None, pattern="^(watching|hit_limit|not_hit)$"),
    persistent_only: bool = False,
):
    if strategy_id != "limit-up-ambush":
        raise HTTPException(status_code=404, detail="该策略没有盘中预警复盘")
    return repository.alert_history(
        strategy_id,
        alert_date=date,
        result=result,
        persistent_only=persistent_only,
    )


@app.get("/api/strategies/{strategy_id}/t1-review/latest")
def latest_t1_review(strategy_id: str) -> dict:
    """Return the latest completed T+1 review day for formal recommendations."""
    if strategy_id not in STRATEGY_INSTANCES:
        raise HTTPException(status_code=404, detail="策略不存在")
    review_date, reviews = repository.latest_t1_reviews(strategy_id)
    return {
        "strategy_id": strategy_id,
        "review_date": review_date,
        "reviews": [
            {
                "recommendation_at": review["recommendation_at"],
                "trade": review["trade"].model_dump(mode="json"),
            }
            for review in reviews
        ],
    }


@app.get("/api/strategies/history")
def all_strategies_history(
    limit: int = Query(80, ge=1, le=300),
    date_from: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    date_to: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    """跨策略的历史 run 汇总，用于"今日各策略推荐"视图。"""
    return {"runs": repository.list_recent_runs_all_strategies(
        limit=limit, date_from=date_from, date_to=date_to,
    )}


@app.get("/api/strategies/{strategy_id}/run/{run_id}")
def get_historical_run(strategy_id: str, run_id: str):
    """加载某次历史 run 的完整信号，右侧 inspector 用。"""
    if strategy_id not in STRATEGY_INSTANCES:
        raise HTTPException(status_code=404, detail="策略不存在")
    run = repository.get_run(run_id)
    if (
        run is None
        or run.strategy_id != strategy_id
        or run.mode != "live"
        or run.execution_status == "sample"
        or run.capture_origin != "scheduled"
    ):
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


@app.post("/api/strategies/{strategy_id}/run")
def run_strategy(strategy_id: str, mode: str = Query("live", pattern="^live$")):
    instance, _ = _resolve(strategy_id)
    service = _live_service(
        instance,
        history=AkshareHistoryProvider(),
        intraday=AkshareIntradayProvider(),
        sectors=LiveSectorProvider(),
    )
    try:
        run = service.run(LiveSpotProvider(), mode=mode)
        if run.execution_status == "tradable" and not run.signals:
            setattr(run, "empty_alert", "可执行时段无候选；可能筛选过严或市场无满足条件的票。")
        return run
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"策略运行失败：{exc}") from exc


@app.post("/api/strategies/{strategy_id}/preview")
def preview_strategy(strategy_id: str, mode: str = Query("live", pattern="^live$")):
    """无论是否尾盘都跑一遍，返回合格候选 + 接近合格的实时近失分股票。"""
    instance, _ = _resolve(strategy_id)
    service = _live_service(
        instance,
        history=AkshareHistoryProvider(),
        intraday=AkshareIntradayProvider(),
        sectors=LiveSectorProvider(),
    )
    try:
        return service.preview(
            LiveSpotProvider(), mode=mode,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"预览失败：{exc}") from exc


@app.post("/api/strategies/run-all")
def run_all_strategies(mode: str = Query("live", pattern="^live$")):
    """对所有 P1-P4 + V1 同时跑一次，结果横向对比。"""
    try:
        snapshots = LiveSpotProvider()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"行情获取失败：{exc}") from exc

    history = AkshareHistoryProvider()
    intraday = AkshareIntradayProvider()
    sectors = LiveSectorProvider()
    active_services = {
        strategy_id: _live_service(
            instance,
            history=history,
            intraday=intraday,
            sectors=sectors,
        )
        for strategy_id, instance in STRATEGY_INSTANCES.items()
    }

    results: dict[str, dict] = {}
    for strategy_id, service in active_services.items():
        try:
            run = service.run(snapshots, mode=mode)
            results[strategy_id] = run.model_dump(mode="json")
        except Exception as exc:
            results[strategy_id] = {"error": str(exc), "strategy_id": strategy_id}
    return {"runs": results, "mode": mode}


@app.post("/api/backtests/t1/collect")
def collect_t1_outcomes() -> dict:
    trades = T1OutcomeCollector(repository).collect_due()
    return {"collected": len(trades), "trades": trades}


@app.get("/api/backtests/t1/recent")
def recent_t1_outcomes() -> dict:
    trades = repository.recent_t1_outcomes()
    return {"trade_count": len(trades), "trades": trades}


web_dir = Path(__file__).resolve().parents[1] / "web"
if web_dir.is_dir():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
