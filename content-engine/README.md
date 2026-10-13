# content-engine

自动化中文内容流水线的骨架。采集、关键词预筛、LLM 精选与生成、受约束
排版、确定性配图、人工审核台、微信公众号投递——所有通用机制都在这里。

**`packs/<name>/` 决定写什么。** 换点子不需要改代码。

## 适合做什么

任何「自动发现 + LLM 二次加工 + 多平台发文 + 人工把关 + 公众号落地」的
场景都能复用：

- AI 工具/开源项目/趋势日报（默认 `packs/ai-news/`）
- 财经资讯摘要、副业机会、读书笔记
- 学术论文大众化解读、播客/视频文案转写
- 行业周报、竞品动态、政策追踪

不适合：纯转发搬运、需要人主动搜索、需要登录后操作的源；这类仍可单
独加 `sources/<>.py` 适配器接入，但本骨架不保证安全或合规。

## 目录布局

```
content-engine/
├── engine/              # 骨架代码。** 不要在这里改业务规则 **
│   ├── pack.py          # ContentPack 加载与验证
│   ├── cli.py           # 入口；所有子命令都加载 pack
│   ├── generation.py    # LLM 调用的「机制」
│   ├── scoring.py       # 预筛 + LLM 精选
│   ├── templates.py     # 写作简报 + 平台骨架组装
│   ├── quality.py       # 硬拒/劝告闸门
│   ├── sources/         # 采集器适配器
│   ├── visuals/         # 配图（Pillow + 远程生图）
│   ├── wechat/          # 微信公众号素材上传 + 草稿
│   └── review/          # Flask 审核台
├── packs/
│   └── ai-news/         # 示例 pack。复制一份改名就开始做新点子
│       ├── pack.toml
│       ├── keywords.toml
│       ├── quality.toml
│       ├── style.toml
│       └── prompts/
│           ├── scoring.md
│           ├── factual_draft.md
│           ├── editorial_voice.md
│           └── weekly_recap.md
├── config.example.toml  # 运行时配置：路径、限流、调度
├── deploy/systemd/      # timer + service 单元
└── tests/engine/        # 940+ 测试
```

## 核心抽象：ContentPack

骨架本身不知道你在写什么。打包方式：

| 类别 | 配置入口 | 决定什么 |
|---|---|---|
| 发现 | `config.toml` 里的 `[[rss_feeds]]` + `source_limits` | 抓哪些源、抓多少条 |
| 预筛词表 | `keywords.toml` | 哪些词算「有趣/有用/演示类」 |
| 热度归一 | `keywords.toml::[heat.sources.*]` | 1000 stars 算几分 |
| 栏目路由 | `pack.toml::[[columns]]` | 源/关键词 → 写到哪个栏目 |
| 写作简报 | `pack.toml::[brief]` | 任务陈述、覆盖清单 |
| 平台骨架 | `pack.toml::[platform_skeletons]` | 四个平台的起始模板 |
| 质量闸 | `quality.toml` | 禁词、高风险话题、长度阈值 |
| 视觉风格 | `style.toml` | 封面模板的排版 + 配色 |
| 模型提示词 | `prompts/*.md` | 实际写进 LLM 上下文的内容 |

加新栏目、改禁词、调主题色、换提示词——**只动 `packs/<name>/` 里的文
件，骨架代码完全不用碰**。`engine/pack.py` 在加载时校验每个字段，启动
期就拒绝格式错的 pack。

## 跑起来

### 用现成的 AI 资讯 pack

```bash
cd /opt/content-engine       # 部署位置可换
cp config.example.toml config.toml
$EDITOR config.toml          # 主要改 pack_dir / output_dir / source_limits

# 任一种方式
python -m engine.cli --config config.toml daily
# 或者显式指定 pack
python -m engine.cli --config config.toml --pack packs/ai-news daily
```

### 启动审核台

```bash
sudo install -m 600 /dev/null /opt/content-engine/image.env   # API key 专用
sudoedit /opt/content-engine/image.env
sudo systemctl enable --now ai-content-review.service
# http://127.0.0.1:8765
```

### 部署

`deploy/systemd/ai-content-loop.timer` 是 `OnCalendar=hourly`。要每天跑就
改成 `OnCalendar=*-*-* 08:00:00 Asia/Shanghai`。一次性的「双调度」是个坑
——别同时装 timer 和 cron 触发同一个脚本。

## 做新点子：分步走

举例：做一个「AI 副业机会日报」。

### 1. 复制 pack

```bash
cp -r packs/ai-news packs/side-hustle
```

### 2. 改 `pack.toml`

```toml
name = "side-hustle"                              # 必须 2-40 字符、小写 + 数字 + 短横
default_column = "机会速览"

[[columns]]
name = "机会速览"
match_sources = []                                # 都靠关键词路由
match_keywords = ["副业", "赚钱", "side hustle", "变现", "副业推荐"]
guide = """- 核心问题：...  """

[brief]
task = "写一条普通人能跟上的副业机会，要求具体、可执行、有风险提示。"
checklist = [ ... ]                               # 写清楚覆盖要素

[balance]                                         # 这次不要 arxiv，删掉
research_sources = []
practical_sources = ["rss_appinn_ai", "rss_36kr"] # 改名匹配你的实际源
practical_prefixes = []
max_research_per_batch = 0

[platform_skeletons]                              # 改每个平台的起始模板
wechat = """# {title}\n\n栏目：{column}\n\n... """
```

### 3. 改 `keywords.toml`

把 `groups.clarity` / `groups.fun` 这些维度换成符合新主题的词。`weights`
必须加总 1.0。`heat.sources` 也得换——副业源没有「GitHub stars」概念。

### 4. 改 `quality.toml`

副业类容最容易踩「保证赚钱」红线。把 `banned_promises` 加严；副业推荐
的 `synthetic_title` 句式和 AI 资讯不同，把 `synthetic_title_patterns`
按新主题调整。

### 5. 改 `prompts/*.md`

这是最影响输出味道的一步。重写 `editorial_voice.md` 的人设、重写
`factual_draft.md` 的事实抽取结构。`scoring.md` 的打分维度按新主题调整。

### 6. 改 `style.toml`

新主题换配色。`layout` 不能动（只能 `split` / `verdict` / `takeaway`），
但配色、模板名都自由。

### 7. 验证

```bash
python -m engine.cli --config config.toml --pack packs/side-hustle init
# 然后手动跑 ingest 试一条，看输出是否对劲
python -m engine.cli --config config.toml --pack packs/side-hustle ingest
python -m engine.cli --config config.toml --pack packs/side-hustle score
python -m engine.cli --config config.toml --pack packs/side-hustle build-queue
python -m engine.cli --config config.toml --pack packs/side-hustle generate-drafts
```

### 8. 写新 pack 的测试

`tests/engine/` 已经覆盖骨架。pack 自己的行为建议单测——比如某个栏目
路由规则、某条禁词模式、某个平台骨架的占位符替换。在 `tests/packs/` 下
加：

```python
from engine.pack import load_pack

def test_side_hustle_blocks_guarantee_phrases():
    pack = load_pack("packs/side-hustle")
    assert "保证赚钱" in pack.banned_promises
```

## 安全边界

骨架已经替你挡住的事：

- **模型注入**：`article_layout` 三层校验，文章 HTML 永远由渲染器组装
- **URL 注入**：布局文本里出现 `http://`、`..`、`c:\`、模板占位符都会硬拒
- **路径遍历**：`asset_path` 逐级查符号链接
- **WSGI sandbox**：审核台 systemd `ProtectSystem=strict` + CSP
- **微信投递 fail-closed**：图片上传了但 `draft/add` 失败时，状态置
  `pending`，禁止自动重试，让人去公众号后台核对
- **并发安全**：`publish_queue` 走 claim token + 1 小时租约，崩溃不卡
- **改动即撤销批准**：审核台任何写操作都先吊销 web edition，concurrent
  版本冲突 → 409

## 不变的约束

- **prompt 路径**：`engine.cli` 运行时从 pack 里读提示词，不从包内 `prompts/` 读
- **模板占位符**：只支持 `{title} {column} {url} {source} {min_chars}`；别的
  写错了会在正文里看见
- **layout 类型**：只能是 `split` / `verdict` / `takeaway` 之一
- **配置缺失即失败**：`load_config` 找不到文件直接 `ValueError`，不会回
  到默认值写到奇怪的地方
- **远端 API key 放 `image.env`**：永远不要写进 TOML

## 不在骨架里的事

- 平台账号风控 / 验证码识别
- 视频/播客/图片源的合规（仅文本 RSS 和 REST API 适配器）
- 自动多账号管理
- 阅读量/互动数据的反作弊清洗

要加这些层，开新的 packs/ 之外更可能需要新增 adapter，而不是改骨架。
