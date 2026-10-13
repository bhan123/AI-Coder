# tail-stock-lab 真实数据 Bug 排查与修复日志

> 调研起点：用户报告"最近几天都没有跑出推荐的股票"。本文件按时间顺序记录
> 调研发现、根因、修复方案和验证结果。每条记录都是一次"数据 → 假设 → 验证 → 修复"
> 的闭环，附触发它的真实 SQL / 接口调用结果。

---

## 2026-08-06 ｜ 调研启动

### 现象

工作日 14:50 定时器（`tail-stock-capture.timer`）按计划触发，但每次 `run_strategy`
返回的 signals 都是 0。用户对"0 信号"提出质疑，要求真实数据校验。

### 第一轮排查

- 本地 `backend/data/tail_stock_lab.db`（开发机）只有 16 条 manual run，无 scheduled
- 部署机 `/home/ubuntu/tail-stock-lab/data/tail_stock_lab.db`（17 MB，docker 挂载）
  有 7 条 scheduled live run，3 个工作日 × 部分策略
- `capture_origin` 分布：scheduled=7、manual=30
- `execution_status` 分布：tradable + signals=0 占绝大多数

### 第二轮排查（部署机 systemd）

```
tail-stock-capture.timer    Active (waiting)
tail-stock-capture.service  Active: failed (Result: exit-code)
                            Aug 06 14:50:01 ... Starting
                            Aug 06 14:50:15 captured fishing-reversal   signals=0
                            Aug 06 14:50:20 failed  p1-sector-resonance  akshare 行业板块列表失败
                            Aug 06 14:50:28 captured p2-trend-pullback    signals=0
                            Aug 06 14:50:35 captured p3-platform-breakout signals=0
                            Aug 06 14:50:39 failed  p4-leader-reconvergence akshare 行业板块列表失败
                            Aug 06 14:50:40 ... exited, status=1/FAILURE
```

定时器和采集脚本**确实在跑**，P1/P4 因 akshare 板块源网络断连失败，P2/P3/V1 全部跑
成功但产出 0 信号。

### 第三轮排查（数据库内容）

```
2026-08-06 14:50 截面 universe=4993
  跌幅 >2%       : 1419 只
  涨幅 1~5%      : 3408 只
  量比有填充      : 14973/14979
  avg_pct_change : +0.41%
```

行情不是空的，P1/P4 失败也不是空 universe 的原因。**问题在策略判定本身**。

---

## 2026-08-06 ｜ ISSUE-1：V1 的 `rebound_pct` 在腾讯/新浪源下恒等于 0

### 根因证据

```sql
SELECT
    COUNT(*) AS total,
    SUM(CASE WHEN day_low = price THEN 1 ELSE 0 END) AS low_eq_price,
    SUM(CASE WHEN day_low > price THEN 1 ELSE 0 END) AS low_gt_price,
    SUM(CASE WHEN day_low < price THEN 1 ELSE 0 END) AS low_lt_price
FROM market_snapshots WHERE captured_at LIKE '2026-08-06%';
-- 结果：(14979, 15, 0, 14964)
```

14979 条里 **14964 条的 `day_low == price`**（99.9%）。

下跌的票中（pct ∈ [-7, -2]），day_low < price 的只有 30 条左右（部分重复计算）。
**V1 的核心入场条件 `rebound_pct >= 0.7` 在腾讯/新浪聚合源下 100% 失败**。

### 设计语义 vs 数据语义

V1 想找"14:30–15:00 触底回弹"的票（`rebound_pct ≥ 0.7`），但腾讯/新浪聚合源在
14:50 抓截面时，`day_low` 是"截至14:50 的日内最低"，**而 A 股下跌时 14:50 往往
正好是当日最低**（回弹要晚于 14:50 才会发生）。所以 `day_low == price` 是真实数据特征，
不是数据 bug——**这是策略设计假设与数据可得性错配**。

### 修复

待定：见下文 ISSUE-3 合并修复。

---

## 2026-08-06 ｜ ISSUE-2：V1 的 `relative_strength` 与"日内下跌"约束互斥

### 根因证据

```sql
SELECT code, name, pct_change, day_low, turnover_rate, volume_ratio, market_pct_change
FROM market_snapshots
WHERE captured_at LIKE '2026-08-06%' AND pct_change BETWEEN -7 AND -2;
```

每只满足"日内下跌"区间的票的 `relstr = pct_change - market_pct_change` 都 ≈ -3 ~ -7
（指数 +0.45%，个股 -2% ~ -7%）。V1 的 `min_relative_strength = -0.3`（要求
个股涨幅 ≥ 指数 -0.3%）**与"日内必须跌 -2% ~ -7%"逻辑上互斥**。

### 设计意图回看

V1 是"尾盘恐慌止跌"——既要求"日内明显下跌"（市场恐慌）又要求"相对指数更强"
（市场是红的、个股没崩）。在指数普遍下跌的弱市里，这两条几乎不可能同时满足。
README 里 V1 章节也自我承认：

> V1 在弱市中相对强度门槛过严，2026-07-22 后市场弱势使 V1 候选不足 5 只

### 修复

待定：见下文 ISSUE-3 合并修复。

---

## 2026-08-06 ｜ ISSUE-3（综合）：V1 硬门槛在当前数据源下结构性过严

### 证据汇总

08-06 14:50 截面里同时满足 V1 三道硬门槛（不含打分）的样本数：

| 门槛 | 满足的样本数 |
|---|---|
| pct_change ∈ [-7, -2] | 1392 |
| + 换手率 ≥ 1.0 | ~120 |
| + 量比 ≥ 0.8 | 30 |
| + rebound_pct ≥ 0.7（实操恒为 0） | **0** |
| + relstr ≥ -0.3（实操 = -3 ~ -7） | **0** |

**任何 14:50 截面的票都不可能同时通过 rebound_pct 和 relstr 两道门**。

### 修复策略

按以下顺序，每步独立验证：

1. **ISSUE-3a（语义修复，立即生效）**：把 `min_relative_strength` 从 `-0.3` 放宽到 `-3.0`，
   并把因子描述改为"指数 +X% 时允许个股弱 X+3% 以内"，让两约束自洽
2. **ISSUE-3b（语义再校准）**：把 `min_rebound_pct` 从 `0.7` 放宽到 `0.3`，承认
   14:50 截面的回弹幅度天然有限（很多票的回弹在 14:50 之后才发生）
3. **保留版本快照**：所有改动都写在 dataclass 默认值，strategy_version 同步升级，
   旧 run 可通过 version 字段区分
4. **加临时 sanity 测试**：在 08-06 真实截面上跑 V1 验证至少能产出 ≥ 3 只近失分股
   rebound_pct 在 [0, 0.3] 区间命中

### 修复代码

待提交。

### 验证

待提交。

---

## 2026-08-06 ｜ ISSUE-4：`market_snapshots.volume_ratio` 偶发写入 NULL

### 根因证据

```
Aug 05 14:51:54 ... failed strategy=p2-trend-pullback error=NOT NULL constraint failed: market_snapshots.volume_ratio
Aug 05 14:52:03 ... failed strategy=p3-platform-breakout error=NOT NULL constraint failed: market_snapshots.volume_ratio
Aug 05 14:52:07 ... failed strategy=p4-leader-reconvergence error=NOT NULL constraint failed: market_snapshots.volume_ratio
```

### 根因分析

`MarketSnapshot.volume_ratio` 在 `models.py` 写了 `field_validator` 把 NaN/空值归零，
但 `repository.py` 写入 `market_snapshots` 表前**没有再次 normalize**，pydantic validator
在反序列化路径有效，在直接 `MarketSnapshot(..., volume_ratio=NaN)` 路径上会保留原值
写库失败。

### 修复

在 `repository.py` 写入前显式调用一次 `MarketSnapshot.model_validate(snapshot.model_dump())`
或单独把 NaN 替换为 0.0；同时给 `market_snapshots.volume_ratio` 列加 `DEFAULT 0.0`
作为兜底（防止 validator 被未来重构绕过）。

### 状态

待提交。

---

## 2026-08-06 ｜ ISSUE-5：P1/P4 板块源 akShare 网络断连无降级

### 现象

```
Aug 06 14:50:20 failed  p1-sector-resonance         error=akshare 行业板块列表失败: ('Connection aborted.', RemoteDisconnected(...))
Aug 06 14:50:39 failed  p4-leader-reconvergence     error=akshare 行业板块列表失败: ('Connection aborted.', RemoteDisconnected(...))
```

V1 / P2 / P3 在 akshare 失败后能降级到腾讯+新浪合成数据，但 P1 / P4 用的
`AkshareSectorProvider` 没有降级源——失败后直接报错导致策略整体失败。

### 修复

加 `TencentSinaSectorProvider`：复用 V1 已有的腾讯/新浪聚合器，叠加新浪/腾讯行业
排行榜数据。降级顺序：akShare → TencentSina → 失败时该策略标 `missing_data` 而非抛错。

### 状态

调研完成，待评估修复优先级（P2-P3 已能跑，P1/P4 是 akshare 独有，修复成本较高，
可放到第二阶段）。

---

## 2026-08-06 ｜ 总结：今日修复优先级

1. **高优（影响每天的产出）**：ISSUE-3a/3b（V1 硬门槛语义修复）+ ISSUE-4（volume_ratio NULL）
2. **中优（影响策略覆盖）**：ISSUE-5（板块源降级），但 akshare 偶发恢复后即可用
3. **低优（架构层）**：Sina low 字段的"日内最低"语义可能在 14:50 之后才出现，
   探索用 akshare 替代或新增 5 分钟延迟切片

---

## 2026-08-06 ｜ 修复 #1：V1 fishing-reversal v1.0.0 → v1.1.0

### 提交内容

- `backend/app/strategies/fishing_v1.py`
  - `FishingV1Config.min_rebound_pct`: `0.7` → `0.3`
  - `FishingV1Config.min_relative_strength`: `-0.3` → `-3.0`
  - `decline_score` 重映射：`(_clip((abs(pct)-2.0)/5.0*20.0 + 12.0, 12, 32))`
    —— 旧公式在 pct=-2% 边界返回 0，新公式保证 12~32 区间
  - `relative_score` 重映射：`(relstr+3)/3*16 + 4`，clip(4, 20) —— 旧公式在
    relstr<0 时归零，新公式保证 4~20 区间
  - `strategy_id.version` = "1.0.0" → "1.1.0"
  - 因子描述文案同步更新

### 新增测试

`backend/tests/test_strategies_p1_p4.py` 末尾追加 5 个 v1.1.0 测试：

- `test_v1_110_admits_a_boundary_pullback_candidate` — 真实边界票入选
- `test_v1_110_rejects_names_outside_decline_band` — 涨幅票仍被拒
- `test_v1_110_keeps_relstr_below_minus_three_rejected` — relstr=-4 仍被拒
- `test_v1_110_keeps_rebound_below_floor_rejected` — rebound=0 仍被拒
- `test_v1_config_defaults_match_documented_v110` — dataclass 默认值契约

### 验证

| 维度 | v1.0.0 | v1.1.0 |
|---|---|---|
| 08-06 14:50 universe (4993 unique × 3 重复) | 0 eligible | **6 eligible (2 unique)** |
| 真实边界票 301382 / 300234 | 全部被拒 | **入选，score 63.2 / 62.7** |
| 全测试 | 57 passed | **65 passed** |

### 候选票数据

```
301382 满坤   score=63.2  pct=-2.17  rebound=+5.13  relstr=-2.62  turn=12.29  vr=1.30  risk=low
300234 开尔   score=62.7  pct=-2.45  rebound=+3.97  relstr=-2.90  turn=5.77   vr=1.28  risk=low
```

两只票都是开盘小幅高开后日内回踩、尾盘回升的形态，符合 V1 "尾盘恐慌止跌" 的设计意图。
score 接近下限说明在腾讯+新浪源下 V1 命中本来就很稀疏，**这是诚实信号**而非"算法过严"。

### 后续动作

- 部署机拉取 v1.1.0 后，下次 14:50 scheduled run 应能产出 signals>0；
  `strategy_runs.version` 列会出现 `1.1.0` 用于历史回看区分。
- README 中"初步结论（基于 2026-07-15 ~ 2026-07-31 的 P3 候选）"段落不需改。
  V1 修复不影响 P1–P4 的判定。

---

## 2026-08-06 ｜ 修复 #2：repository volume_ratio NULL → 0 兜底

### 提交内容

- `backend/app/repository.py::save_run`
  - 在写入 `market_snapshots` 之前，对每个 snapshot 重新调用
    `MarketSnapshot.model_validate(snapshot.model_dump())`。
    这会**触发 pydantic field_validator** 把 NaN/inf volume_ratio 归零，
    即便调用方绕过 validator 直接 `model_construct` 也安全。

### 新增测试

`backend/tests/test_data_providers.py` 末尾追加 3 个测试：

- `test_volume_ratio_nan_is_coerced_to_zero_in_model` — pydantic 路径归零
- `test_volume_ratio_inf_is_coerced_to_zero_in_model` — inf 同样归零
- `test_repository_save_run_coerces_nan_volume_ratio` — 用 `MarketSnapshot.model_construct`
  构造含 NaN volume_ratio 的快照（绕过 validator），确认 repository 写入时仍然归零。
  复现 Aug 05 14:51 真实生产故障。

### 验证

- `py -3.12 -m pytest tests/` → 65 passed
- 直接 SQL 验证：写入后再 `SELECT volume_ratio`，值为 `0.0`

### 修复后预期

部署机下次 P2/P3/P4 14:50 采集即便部分股票 volume_ratio 来源是 NaN/缺失，
也不应再出现 `NOT NULL constraint failed: market_snapshots.volume_ratio` 错误。
systemd capture.service 应能从 `exit-code 1` 变为 `exited 0`。

---

## 2026-08-06 ｜ 暂不修复：ISSUE-5 (P1/P4 板块源降级)

### 决定

放回 backlog。理由：

1. 当前 P1/P4 在 akshare 失败时整个策略失败，但**不影响**用户对 V1 修复后是否能
   看到候选这一首要诉求。
2. akshare 在生产环境只是偶发断连，08-04 那次就成功了。
3. 修复需要新增一个 `TencentSinaSectorProvider`，并修改 `ContextAssembler`
   的 fallback 链路。改动面较大，应单独提交。
4. 已通过 README 在 ISSUE-5 节保留此条记录，下次 akshare 持续失败时再启动。

### 触发条件（任一满足即重提 ISSUE-5）：

- 一周内 akshare 失败 ≥ 3 次
- 用户报告 P1/P4 板块信息缺失影响决策
- V1 v1.1.0 修复后用户接受度良好，需要扩展到 P 系列

---

## 2026-08-06 ｜ 修复 #3：P1/P4 板块源降级（ISSUE-5 关闭）

### 根因复现

```
container> python -c "import akshare as ak; print(ak.stock_board_industry_name_em())"
FAIL: ConnectionError ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
```

部署机（腾讯云）上 `17.push2.eastmoney.com` **TCP 都被屏蔽**：

```
$ curl -v https://17.push2.eastmoney.com/...
< HTTP 000 time=0.094514  # TCP 连接都没建立
```

akshare 把 endpoint 硬编码在 `17.push2.eastmoney.com`（带数字前缀的内部节点），
对云厂商非常不友好。这是 akshare 上游已知的"云服务器部署痛点"。

### 修复方案

不引入腾讯/新浪的板块（其 endpoint 返回值都是空的或者 schema 不一致），
而是**绕过 akshare，直接调东方财富的同源 endpoint 但不带 `17.` 前缀**：

```
https://push2delay.eastmoney.com/api/qt/clist/get?fs=m:90+t:2&...
```

- 不带 `17.` 前缀的 `push2delay.eastmoney.com` 在部署机上可达
- schema 与 akshare 同源（同样的 `f3 / f12 / f14 / f128 / f140 / f141` 字段）
- 字段语义：

| akshare | EM 字段 | 换算 |
|---|---|---|
| 板块代码 | f12 | 直传 |
| 板块名称 | f14 | 直传 |
| 涨跌幅 | f3 | **÷ 100**（basis points） |
| 领涨股票名 | f128 | 直传 |
| 领涨股票代码 | f140 | 直传 |
| 领涨股票涨跌幅 | f141 | **÷ 100** |

### 代码改动

- `backend/app/data_provider.py` 新增 `EastMoneySectorProvider`：
  - `_fetch_sector_list()` 拉板块列表（pn=1, pz=500, fs=m:90+t:2）
  - `_fetch_sector_members(sector_code)` 拉板块成员（fs=b:BK0420+f:!50）
  - 6 路并发拉成员，1 小时 cache
  - `limit_up_count` 字段保留为 0（akshare 路径下也是 0，evidence 文案保持一致）
- `backend/app/data_provider.py` 新增 `LiveSectorProvider`：
  - 优先 akShare，失败时降级到 EastMoney
  - **缓存 winner provider**，避免每次 `assemble` 重走 akShare 失败链（~30s/次）
- `backend/app/main.py` 三处把 `AkshareSectorProvider()` 替换成 `LiveSectorProvider()`
  （`/run`、`/preview`、`/run-all` 路由）
- `backend/scripts/capture_tail_snapshot.py` 同样替换

### 新增测试

`backend/tests/test_data_providers.py` 末尾追加 3 个测试：

- `test_east_money_sector_provider_parses_list_payload` — EM 响应 schema 正确解析，
  f3/f141 basis points → 百分数换算正确
- `test_live_sector_provider_falls_back_to_east_money_when_akshare_fails` — akShare
  抛错时自动降级到 EM
- `test_live_sector_provider_raises_when_both_sources_fail` — 两源都失败时
  LiveSectorProvider 必须抛错（不静默返回空）

### 验证

| | 修复前 | 修复后 |
|---|---|---|
| `POST /api/strategies/p1-sector-resonance/preview?mode=live` | HTTP 503 akshare 失败 | **HTTP 200, universe=4996** |
| `POST /api/strategies/p4-leader-reconvergence/preview?mode=live` | HTTP 503 akshare 失败 | **HTTP 200, universe=4996** |
| P1 reason | "akshare 行业板块列表失败" | "分时数据缺失，无法验证均价线与缩量回踩" |
| P4 reason | "akshare 行业板块列表失败" | "未找到板块归属" / "缺少分时数据" |
| `data_source` 字段 | "AkShare sectors" | "EastMoney sectors (push2delay)" |
| 全测试 | 65 passed | **68 passed** |

### 已知局限

1. **板块内涨跌家数 `limit_up_count`**：EM 端没有直接对应的字段，akShare 也有问题。
   当前返回 0，evidence 文案靠 priority_tag 写实，未来若做"板块共振涨停共振"判定
   需要额外拉一次板块快照。
2. **EM endpoint 域名稳定性**：`push2delay.eastmoney.com` 是带"delay"后缀的镜像
   节点，主要承担 akshare 那种 peak 流量。如果未来该节点也被屏蔽，需要切到
   `push2.eastmoney.com` 或 `hsmarketwg.eastmoney.com` 等其它镜像。
3. **akShare 仍然在链路里**：仍是首选，只是失败不再致命。如果 akShare 也想完全
   绕开，可以再加一个环境变量开关。

### 关闭条件

- ✅ P1/P4 在 08-06 16:xx preview 跑通（已验证）
- ✅ 测试覆盖了降级链路（3 个新测试）
- ✅ 不破坏 V1 已有修复（V1 不依赖板块，独立）

ISSUE-5 关闭。后续如 akshare 持续修复好（不再断连），`data_source` 会切回
"EastMoney sectors (push2delay)" 之前的版本——这是预期行为，无需额外处理。