# hupu_user_crawler

抓取虎扑用户 `19134213076193`（"巴萨主教练弗里克"）在 `/stock` 板块的**所有主贴**，并基于抓取数据训练出多模板写作风格库（skill），用于生成每日股票复盘。

> **当前数据集**：446 条主贴 / 720K 字 / 时间跨度 2025-01-02 → 2026-08-06

---

## 目录

1. [三种抓取来源对比](#三种抓取来源对比)
2. [快速开始](#快速开始)
3. [Cookie 怎么拿](#cookie-怎么拿)
4. [API endpoint 是怎么发现的](#api-endpoint-是怎么发现的)
5. [数据形态](#数据形态)
6. [项目结构](#项目结构)
7. [写作 Skill 使用](#写作-skill-使用)
8. [端到端演示](#端到端演示)
9. [测试](#测试)
10. [安全提示](#安全提示)
11. [后续优化方向](#后续优化方向)

---

## 三种抓取来源对比

| 来源 | URL/Endpoint | 需要登录 | 数据范围 | 限制 |
|------|--------------|---------|----------|------|
| `/stock` 板块分页 | `bbs.hupu.com/stock-{N}.html` | ❌ | 最近 ~500 帖 | 受板块分页深度限制 |
| 个人主页 pageData | `my.hupu.com/{uid}` HTML 里的 JSON | ✅ | **最近 30 帖** | Hupu 服务端硬限 |
| 个人主页 API | `bbs.hupu.com/pcmapi/pc/space/v1/getThreadList` | ✅ | **全量历史**（推荐） | 每页 10 条，需翻页 |

**推荐使用第三种（API）**：`crawl_all_history.py`

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 设置 cookie（从浏览器 DevTools 复制 Cookie 请求头整段字符串）
export HUPU_COOKIE="csrfToken=...; acw_tc=...; u=...; ..."

# 3. 全量抓取（覆盖 2025-01-02 到现在的所有 stock 帖子，~25-40 分钟）
py crawl_all_history.py --until-date 2025-01-02

# 4. 仅枚举 tid（不抓详情页，~1 分钟）
py crawl_all_history.py --summary-only --until-date 2025-01-02

# 5. 只用板块分页抓最近的（无需 cookie，~5-15 分钟）
py run_crawl.py --max-pages 50 --until-date 2025-08-05

# 6. 个人主页 pageData（需要 cookie，但只返回最近 30 条）
py crawl_profile.py
```

输出文件：
- `data/hupu_19134213076193.jsonl` — **当前主数据集**（446 条）
- `data/hupu_19134213076193_stockboard.jsonl.bak` — `/stock` 旧抓的备份（17 条）

---

## Cookie 怎么拿

1. Chrome / Edge 登录虎扑后访问 `https://my.hupu.com/19134213076193`
2. F12 → Network → 刷新页面
3. 点对 `my.hupu.com` 的请求 → Request Headers → 复制 `Cookie:` 后面的**整段字符串**
4. 粘贴到 `HUPU_COOKIE` 环境变量，或用 `--cookie "..."` 传入

⚠️ **安全**：cookie 等同于虎扑账号密码。建议抓完后退出登录或改密码让 cookie 失效。

---

## API endpoint 是怎么发现的

1. **抓 `my.hupu.com/19134213076193` HTML**（个人主页）
2. **提取 HTML 里嵌入的 pageData JSON** — 只包含最近 30 条，server-side 限制
3. **在 HTML 里发现外部 JS bundle**：`w1.hoopchina.com.cn/games/static/pc-myhupu-web/build/bbsIndex_69e95990.js`
4. **分析 JS bundle** 找到 baseURL 配置和 `getThreadList` 的调用：
   ```js
   // 关键代码片段
   {urlName: "getThreadList", path: "euid=" + euid + "&", pageSize: "30"}
   {urlName: "getReplyList",   path: "euid=" + euid + "&maxTime=" + U + "&", pageSize: "10"}
   {urlName: "getRecommendList", path: "euid=" + euid + "&", pageSize: "30"}

   // baseURL 候选
   dev: "http://local.hupu.com:6001",       sit: "http://bbs-sit.hupu.com",
   stg: "https://stg-bbs.hupu.com",          prod: "https://bbs.hupu.com"
   ```
5. **测试发现 `?euid=...&page=N` 支持分页**（每页 10 条，`maxTime` 在 `getReplyList` 才用）

最终 API：`https://bbs.hupu.com/pcmapi/pc/space/v1/getThreadList?euid={uid}&page={N}`

---

## 数据形态

`data/hupu_19134213076193.jsonl`（**446 条主贴 / 720K 字**）：

```json
{
  "thread_id": "641580705",
  "title": "0805复盘：继续修复",
  "content": "【今日操作】\n石头科技 & 国芳集团 & 沪电股份 & 大元泵业 & 科创50etf：持仓不动；\n【今日洞察】\n1.大盘\n1）走势：低开高走，非常强势地突破了3850...\n2）量能：2.66万亿...\n3）赚钱效应：涨跌比3725:1621...\n2. 板块\n1）证券&金融科技：...\n3. 个股\n1）沪电股份：...\n【写在最后】\n免责声明...",
  "author": "巴萨主教练弗里克",
  "author_uid": "19134213076193",
  "post_time": "2025-01-02T09:27:41",
  "url": "https://bbs.hupu.com/641580705.html",
  "fetched_at": "2026-08-06T16:31:58"
}
```

### 文风特征（446 条统一）

- **标题模板**：`MMDD复盘：xxx`（盘后总结）/ `MMDD盘中：xxx`（盘中快评）/ `MMDD盘前：xxx`
- **结构**：`今日操作 → 今日洞察（大盘/板块/个股）→ 写在最后`
- **核心持仓**：石头科技、国芳集团、沪电股份、大元泵业、科创50ETF
- **数据驱动**：每个观点配量价/技术位/百分比
- **关键术语**：反弹/修复/回踩/缩量/高低切/抱团/主线/破位/恐慌盘

### 时间分布（按月）

| 月份 | 帖数 | 月份 | 帖数 |
|------|-----|------|-----|
| 2025-01 | 22 | 2025-12 | 21 |
| 2025-02 | 33 | 2026-01 | 20 |
| 2025-03 | 40 | 2026-02 | 14 |
| 2025-04 | 41 | 2026-03 | 23 |
| 2025-05 | 27 | 2026-04 | 20 |
| 2025-06 | 21 | 2026-05 | 18 |
| 2025-07 | 22 | 2026-06 | 21 |
| 2025-08 | 21 | 2026-07 | 22 |
| 2025-09 | 22 | 2026-08 | 4 |
| 2025-10 | 16 | | |
| 2025-11 | 18 | | |

字数分布：最短 58 字（"盘中"快评），最长 5092 字，中位 1586 字。

---

## 项目结构

```
hupu_user_crawler/
├── config.py                    # 集中配置（cookie 从 HUPU_COOKIE 环境变量读取）
├── crawler.py                   # /stock 板块抓取 + 通用请求/解析工具
├── crawl_profile.py             # 个人主页 pageData 抓取（30 条限制）
├── crawl_all_history.py         # API 分页抓取（推荐，支持全量历史）
├── profile_parser.py            # 解析个人主页 pageData JSON
├── run_crawl.py                 # /stock 抓取的 CLI 入口
├── probe_profile.py             # 探测脚本（保存个人主页 HTML 到本地分析）
├── demo_skill.py                # 端到端演示：加载模板 + 输出可粘贴的 prompt
├── tests/                       # 18 个单元测试（全部通过）
│   ├── test_filter.py           # 解析 + 抓取逻辑
│   ├── test_profile_parser.py   # pageData JSON 解析
│   └── test_profile_crawler.py  # 个人主页抓取
├── requirements.txt
├── README.md                    # 本文件
├── data/
│   ├── hupu_19134213076193.jsonl                # 当前数据集（446 条主贴）
│   └── hupu_19134213076193_stockboard.jsonl.bak # /stock 旧抓的备份（17 条）
├── skill/                       # 写作风格 skill 库
│   ├── README.md                # skill 使用说明
│   ├── selector.md              # 模板选择决策树
│   ├── templates/               # 6 个模板（每个含风格规则+结构+few-shot+调用 prompt）
│   │   ├── 01_bounce_recovery.md     反弹/修复日
│   │   ├── 02_correction.md          大跌/恐慌日
│   │   ├── 03_sideways_rotation.md   震荡/轮动日
│   │   ├── 04_operation_hold.md      重大调仓日
│   │   ├── 05_intraday.md            盘中快评
│   │   └── 06_premarket.md           盘前预判
│   └── examples/                # 8 个真实历史帖（few-shot 用）
└── .claude/
    └── skills/hupu-stock-recap/SKILL.md   # Claude Code skill 入口
```

---

## 写作 Skill 使用

### 6 个模板速查

| 模板 | 适用 | 字数 |
|------|------|------|
| 01_bounce_recovery | 反弹/修复/企稳日 | 1500-3000 |
| 02_correction | 大跌/恐慌/破位日 | 1500-3000 |
| 03_sideways_rotation | 震荡/缩量/轮动日 | 1200-2000 |
| 04_operation_hold | 重大调仓日 | 1500-3500 |
| 05_intraday | 盘中/午盘快评 | 200-500 |
| 06_premarket | 盘前预判 | 300-800 |

### 快速流程

1. **读** `skill/selector.md`，根据今日市场和时点选模板
2. **打开**对应的 `skill/templates/0X_xxx.md`
3. **复制**模板里的「调用 prompt」段
4. **替换** `{用户输入：...}` 为今日真实数据
5. **粘贴**到 Claude API / claude.ai，输出风格化复盘

### 模板选择决策树

```
今天要写什么时点？
│
├── 盘前（开盘前）
│   └─→ 模板 06：盘前预判
│
├── 盘中/午盘/收盘后短评
│   └─→ 模板 05：盘中快评
│
└── 收盘后完整复盘
    │
    今日市场状态？
    │
    ├── 大盘放量涨/板块普涨/跌停家数极少
    │   └─→ 模板 01：反弹修复
    │
    ├── 大盘放量跌/跌停家数暴增/前期主线崩盘
    │   └─→ 模板 02：下跌调整
    │
    ├── 大盘窄幅震荡/量能萎缩/板块轮动快
    │   └─→ 模板 03：震荡轮动
    │
    └── 今日有大动作（加仓/减仓/调仓）
        └─→ 模板 04：操作持仓
```

**复合判断**：满足多个条件才选对应模板。例如"涨幅 0.8% + 缩量 + 板块轮动" → 震荡轮动而不是反弹修复。

### 每个模板的结构

- **风格规则**（主旋律、核心叙事、关键术语）
- **标题模板**（含变体）
- **内容结构**（段落纲要 + 字数要求）
- **Few-shot 示例**（1-2 条真实历史帖完整正文）
- **调用 prompt**（直接复制粘贴用，含「输出格式」）
- **反模式**（避免这些写法）

### Claude Code skill

`.claude/skills/hupu-stock-recap/SKILL.md` 已注册。在 Claude Code 中可以直接调用（具体调用方式取决于 Claude Code 的 skill 调用机制）。

---

## 端到端演示

```bash
py demo_skill.py
```

模拟一次完整调用：
1. **选模板**：根据 selector.md 决策树
2. **加载模板**：从 `skill/templates/01_bounce_recovery.md` 读「调用 prompt」段
3. **填数据**：替换 `{用户输入：...}` 为今日真实行情
4. **输出**：完整 prompt（可粘贴到 Claude API 或 claude.ai）

演示输出示例（节选）：

```
Step 1: 模板选择（按 selector.md 决策树）
  - 时点 = 收盘后
  - 大盘 +0.8%（涨幅 > 0.5%）
  - 量能放量、跌停少 → 满足「反弹修复」条件
→ 选模板: 01_bounce_recovery

Step 4: 完整 prompt（可粘贴到 Claude API/claude.ai）
======================================================================
你是虎扑用户「巴萨主教练弗里克」的写作风格模仿助手。请基于以下
今日市场数据，按「反弹修复」模板写一篇 MMDD 复盘帖：

## 今日数据
- 上证指数：3890 点（+0.8%，+30 点）
- 深成指：12500 点（+1.2%，+150 点）
- 成交量：2.5 万亿（较 5 日均 +20%，显著放量）
- ...

## 写作要求
1. **标题**：MMDD 复盘：{反弹延续/继续修复/...}
2. **结构**：[今日操作 / 今日洞察·大盘·板块·个股 / 写在最后]
3. **风格**：不因乐观忽视风险；强调"反弹 vs 反转"区分
...

## 参考样例
[0804 复盘 + 0805 复盘 完整原文]
======================================================================

总字数: 857 字符（约 285 tokens）
```

---

## 测试

```bash
py -m pytest tests/ -v
```

**18 个测试全部通过**：

```
tests/test_filter.py
  test_parse_thread_list_extracts_both_items
  test_filter_target_user_by_uid
  test_parse_main_post_extracts_title_and_content
  test_parse_main_post_ignores_reply_authors
  test_parse_main_post_returns_none_for_empty
  test_crawl_stops_when_all_posts_older_than_until_date
  test_crawl_continues_when_some_posts_newer_than_until_date
  test_crawl_skips_already_seen_thread_ids
  test_crawl_continues_through_empty_pages_when_until_date_set   # 关键 bug 回归

tests/test_profile_parser.py
  test_parse_profile_page_extracts_all_posts
  test_filter_stock_only_returns_stock_board
  test_post_titles_have_correct_format
  test_post_summary_is_present
  test_invalid_html_returns_empty
  test_parse_full_real_profile_structure

tests/test_profile_crawler.py
  test_crawl_profile_filters_to_stock_only
  test_crawl_profile_skips_existing_tids
  test_crawl_profile_handles_failed_profile_fetch

============================= 18 passed in 0.23s ==============================
```

---

## 安全提示

- **Cookie 风险**：cookie 等同于虎扑账号密码。建议抓完后：
  1. 在 https://passport.hupu.com 退出登录（让 cookie 失效）
  2. 或修改密码强制下线所有会话
- **代码安全**：cookie 通过 `HUPU_COOKIE` 环境变量传入，从不写入代码或 git
- **请求频率**：默认 3-5 秒/请求间隔，对 Hupu 友好；分页 API 额外 sleep 2 秒
- **断点续传**：JSONL 增量写入；中断后重跑自动跳过已抓 thread_id

---

## 后续优化方向

1. **真实 fine-tune**：把 446 条转成 `{"messages": [...]}` 格式，上传 Anthropic API 训练专属模型（成本几十到几百美元，风格迁移最准，长期调用成本低）
2. **风格精炼**：从每个模板抽更多 few-shot 示例（3-5 条），覆盖更多细分场景
3. **行情展望模板**：增加「月初/季初行情展望」模板（如"9月行情展望：抓紧主升行情中的机会"）
4. **持仓追踪**：建立持仓股的技术位档案（沪电股份 123 压力、石头科技 108/106 支撑等），让模板引用更精准
5. **自动评分**：写一个评估脚本，对生成的复盘 vs 历史帖做风格相似度打分（BLEU/embedding similarity）
6. **市场状态自动分类**：训练一个分类器，根据今日指数/成交量自动选模板，替代手动判断

---

## 许可

仅用于个人研究和学习。未经用户授权抓取他人内容可能违反虎扑服务条款。请尊重原创作者权益。
