# 虎扑论坛板块拥挤度预警系统

项目代号：`hupu-sector-crowding`
当前阶段：**Phase 3 — 端到端可部署**（爬虫 + 分析 + API + H5 + 调度均实现）。
完整设计：[`docs/superpowers/specs/2026-07-09-hupu-sector-crowding-design.md`](../docs/superpowers/specs/2026-07-09-hupu-sector-crowding-design.md)。

---

## 当前已上线的功能

1. `docker compose up -d` 一次性拉起
2. APScheduler：
   - 每个**交易日**（周一到周五）15:30 拉 akshare 同花顺板块指数
   - 每天 9/12/18/21:10 自动抓虎扑 `/stock` 板块
   - 每天 21:30 跑分析流水线 → `daily_metrics` / `item_analysis` / `daily_pipeline_stats`
3. FastAPI 在 `:8000` 提供：
   - `/` H5 全景页（散点图 + 板块列表 + 颜色状态）
   - `/board.html?name=半导体` 单板块详情页（指标 + 时序图 + 当日热帖）
   - `/health` `/overview` `/boards/` `/boards/{name}/latest` `/boards/{name}/history`
4. SQLite 6 张表持久化在 `data/hupu.db`（容器外 / 在 `./data` 卷）
5. **板块词典 + 价格接入**通过 akshare 同花顺，**`board_dict_version` 自动随 seed 更新**

## 目录结构

```
plan/
├── config/
│   ├── boards.json            # 14 个 starter board（akshare 接入后可一键覆盖）
│   ├── boards_extra.json      # 别名 + 排除词
│   └── sentiment_lexicon.json # 60+ 词五档 + 否定词
├── src/
│   ├── crawler/               # Next.js selectors 已验证可用
│   ├── storage/               # schema + connection + persist + upsert
│   ├── analysis/              # sentiment + board_matcher + metrics + state_classifier + pipeline
│   ├── scheduler/             # 5 个 cron job
│   ├── api/                   # FastAPI routes + DB 层 + server
│   └── web/                   # H5（mobile-first）+ assets/{app.js, board.js, style.css}
├── scripts/
│   ├── smoke_test.py          # 部署前连通性自检
│   ├── run_crawler.py         # 手动单轮抓
│   ├── run_daily.py           # 手动单次分析
│   └── seed_sector_dictionary.py   # akshare 接入后启用
├── data/                      # hupu.db 在此（gitignored）
└── tests/                     # 22 passed / 23 skipped（22 unit + 5 fixture 抓真实 Hupu HTML）
```

## 本地验证（无需服务器）

```bash
pip install -r requirements.txt

# 1) 测试总览
py -m pytest tests/ -q

# 2) 启动服务（development）
PYTHONPATH=src py -m uvicorn api.server:app --reload --port 8000

# 浏览器看：
#   http://localhost:8000/         全景
#   http://localhost:8000/board.html?name=半导体
#   http://localhost:8000/overview  JSON
```

## 服务器部署

```bash
git clone <repo> /srv/hupu-sector-crowding
cd /srv/hupu-sector-crowding/plan
docker compose up -d
docker compose logs -f app

# 跑一次连通性自检（在容器里或同机）
docker compose exec app python scripts/smoke_test.py --dump-html /tmp/stock.html

# 或在服务器上独立跑一次（不需要等 21:30）
docker compose exec app python scripts/run_daily.py

# 看 data
sqlite3 data/hupu.db "SELECT board, sent_score, state, confidence FROM daily_metrics ORDER BY crowding_score DESC"
```

## API

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查，返回 `{"status":"ok"}` |
| `GET /overview` | 今日全景：所有 board 最新 daily_metrics + 全局 stats |
| `GET /boards/` | board 列表（= /overview.boards 简版） |
| `GET /boards/{name}/latest` | 单板块最新指标 + 当日 Top 10 热帖 |
| `GET /boards/{name}/history?days=30` | 单板块历史时序 |
| `GET /` `/assets/*` `/board.html` `/backtest.html` | H5 静态资源 |

## H5 状态颜色

| 状态 | 颜色 | 含义 |
|---|---|---|
| 亢奋拥挤 | 红 `#d62728` | Hot>90, Sent>75, Crowd>80 |
| 恐慌拥挤 | 橙 `#ff7f0e` | Hot>85, Sent<25, Crowd>70 |
| 新热启动 | 绿 `#2ca02c` | 70<Hot<90, HeatMomentum>1.5, Sent 55-70 |
| 噪音争吵 | 灰 `#888` | Hot>70 且 |Sent-50|<10 |
| 样本不足 | 浅灰 | 非 Top N 或样本/历史 < 阈值（实际部署后才出现强信号） |
| 无强信号 | 深灰 | 命中条件都不满足 |

冷启动阶段全部会是 "样本不足"（按设计 §11 验收点 8）。

## 还不做的事（明确边界）

- ❌ 智能推送 / 公众号 / Telegram — 设计文档 §12 明确不做
- ❌ 回测页（`backtest.html`）— 占位说明，等价格数据有 60 个交易日后接通
- ❌ 东方财富成分股 fallback（EM 接口在多数代理环境会被拦截，THS 名称列表已够用）

## akshare 集成笔记

设计文档 §6：每个交易日 15:30 拉板块行情。第一版数据源：

| 用途 | 接口 | 沙箱里可用？ |
|---|---|---|
| 板块名称列表 (90 条) | `ak.stock_board_industry_name_ths` | ✓ |
| 板块历史指数 (267 行 × 7 列) | `ak.stock_board_industry_index_ths` | ✓ （**注意要传 start_date/end_date 才会拉到 2026 数据**，不传只到 2024-01） |
| 板块行情 pct / 1d/5d/10d/20d | `compute_pct_changes()` 派生 | ✓ |
| 历史分位 (PriceExtension) | `compute_price_extensions()` | ✓ 增量无未来泄漏 |
| 成分股 | `ak.stock_board_industry_cons_em` | ✗ 多数代理拦截，服务器上可重试 |

## 关键设计决定

- **Top N 高频板块**：每个指标日期仅使用不晚于该日期的、至多 20 个已知 `sector_prices` 交易日计算；
  可用交易日少于 20 个时不产生 Top-N（`pipeline.py:mark_top_n_boards`）。
- **历史分位**：120 日 HotRaw 序列、120 日 pct_change_10d 序列。第一版冷启动期 percentile_rank 没有 history 时返回 0.5，对应 HotScore=50。等 20+ 日数据后 percentile 才有意义。
- **作者 ID 哈希**：所有作者一律 SHA256(uid)[:16]，原始 UID 不存（设计 §9.4）。
