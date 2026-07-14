# Hermes 正文生成与每日调度设计

状态：待实施

## 目标

把现有的“采集、评分、写作简报”流水线补齐为可持续运行的内容生产闭环：

1. 每天北京时间 08:00 自动运行；
2. 每次选择两个从未生成过正文的高分选题；
3. 通过服务器上现有的 Hermes CLI 和 MiniMax-M2.7 生成一篇母稿及公众号、小红书、今日头条、知乎四个平台版本；
4. 自动验证结构、来源链接、长度和高风险表达；
5. 生成失败时自动重试一次；
6. 通过的文章进入人工审核队列，不自动登录或发布到内容平台。

## 非目标

- 不实现微信公众号、小红书、今日头条或知乎的自动登录和自动发布；
- 不保存、复制或重新管理 Hermes 的模型密钥；
- 不运行本地大模型；
- 不在一次失败后无限重试；
- 不重复生成已经处理过的选题。

## 方案选择

采用“确定性 Python 编排 + Hermes 写作大脑 + systemd 调度”：

- Python 负责选题状态、提示词组装、Hermes 子进程调用、超时、重试、JSON 解析、质量检查和原子落盘；
- Hermes 使用自身已有配置调用 MiniMax-M2.7，负责标题、正文、平台改写和语言风格；
- systemd timer 负责每天可靠触发，不让 Hermes cron 通过自然语言临场编排确定性步骤。

未采用的方案：

- 全部交给 Hermes cron：代码少，但幂等、重试、状态和错误定位依赖 Agent 临场执行；
- Python 直连 MiniMax API：控制直接，但绕开 Hermes并重复管理模型配置。

## 目录与产物

服务器继续使用现有目录：

```text
/opt/ai-content-loop/
  config.toml
  repo/
    ai_content_loop/
  data/
    ai_content_loop.sqlite3
  out/
    drafts/
      <topic>.json
    final/
      <topic>.json
    failures/
      <topic>.json
  logs/
```

`out/drafts/` 保存 Hermes 输入简报；`out/final/` 保存通过质量门的完整文章；`out/failures/` 保存两次失败后的错误摘要，不保存模型凭证。

## 状态模型

发布队列使用以下状态：

- `needs_generation`：已生成写作简报，等待 Hermes；
- `generating`：某个带随机令牌的一小时租约正在处理该选题；
- `needs_human_review`：完整文章已生成并通过质量门；
- `generation_failed`：两次生成均失败，需要人工查看。

同一 `dedupe_key` 一旦进入发布队列，后续每日选题不再重复选择。旧版中已经标记为 `needs_human_review` 但还没有 `out/final/` 文件的两条记录，在首次部署时迁移为 `needs_generation`。

领取操作通过 SQLite 条件更新完成，并写入 `claimed_at` 与随机
`claim_token`。状态提交必须同时匹配该令牌，过期 worker 不能覆盖新
worker；崩溃遗留的租约在一小时后由下一次任务回收。

## 每日数据流

```text
采集来源
  → 确定性评分
  → 排除 publish_queue 中已有选题
  → 选择前 2 条
  → 写入 drafts 与 needs_generation
  → Hermes 生成
  → JSON 结构校验
  → 内容质量校验
  → 原子写入 final
  → needs_human_review
```

每天北京时间 08:00 依次执行：

1. `ingest`
2. `score`
3. `build-queue`
4. `generate-drafts`

任一来源采集失败只记录告警并继续。若确定性前置步骤失败，任务退出并保留日志，不调用 Hermes。

## Hermes 调用边界

生成器通过配置中的 Hermes 可执行文件调用：

```text
/home/agentuser/.local/bin/hermes chat -Q -t none -q <prompt>
```

每个选题单独调用，避免一个选题失败污染另一个选题。提示词由版本化的 `prompts/drafting.md`、写作简报和严格 JSON 输出要求组成。

`none` toolset 在当前 Hermes 版本解析为空工具集。写作简报中的所有
来源字段都被标记为不可信证据，Hermes 不得执行其中夹带的指令。生成器
在启动子进程前检查完整命令行大小，为重试反馈预留空间，并避免把提示词、
原始模型输出或外部 stderr 写入失败产物。

Hermes 输出必须包含：

```json
{
  "dedupe_key": "source:id",
  "column": "栏目",
  "master_title": "标题",
  "master_markdown": "母稿",
  "platform_markdown": {
    "wechat": "公众号版本",
    "xiaohongshu": "小红书版本",
    "toutiao": "今日头条版本",
    "zhihu": "知乎版本"
  }
}
```

生成器允许清理 Markdown JSON 代码围栏，但不猜测缺失字段，也不接受 `dedupe_key` 不一致的结果。

## 质量门与重试

每份结果必须满足：

- JSON 可以解析；
- 必填字段齐全且类型正确；
- `dedupe_key` 与输入一致；
- 母稿和四个平台版本均非空；
- 母稿和四个平台版本均保留一手来源链接；
- 标题和正文达到最低长度；
- 不包含保证赚钱、躺赚、稳赚、100% 等承诺；
- 不包含医疗诊断、投资建议或法律意见。

第一次失败后，第二次提示词附带机器可读的失败原因，要求 Hermes 只修复这些问题并重新输出完整 JSON。第二次仍失败时：

- 不再调用模型；
- 写入 `out/failures/<topic>.json`；
- 队列状态更新为 `generation_failed`；
- 每日任务继续处理下一个选题。

## 幂等与文件安全

- `build-queue` 排除所有已在发布队列中的 `dedupe_key`；
- `generate-drafts` 只处理 `needs_generation`；
- 每条记录必须先取得带令牌的 `generating` 租约；并发 worker 只有一个
  能取得租约；
- 已存在且通过验证的 `out/final/<topic>.json` 不重新生成；
- 最终文件先写入同目录临时文件，完成 `flush` 后通过替换操作原子发布；
- 定时任务重跑不会重复调用已成功选题，也不会重复产生费用。

## 配置

生产配置增加：

```toml
hermes_command = "/home/agentuser/.local/bin/hermes"
generation_timeout_seconds = 600
generation_retries = 1
```

`generation_retries = 1` 表示首次失败后额外重试一次，总调用上限为两次。

## 调度与权限

使用 systemd service 和 timer：

- 服务以 `agentuser` 运行；
- `WorkingDirectory=/opt/ai-content-loop/repo`；
- `HOME=/home/agentuser`；
- `UMask=0027`；
- timer 使用 `OnCalendar=*-*-* 08:00:00 Asia/Shanghai`；
- `Persistent=true`，服务器错过时间后启动会补跑；
- 日志写入 journald，并保留应用自身错误摘要。

不使用 `--yolo`，不授予 Hermes sudo 权限。

## 测试与验收

自动化测试覆盖：

- 解析合法 JSON 和代码围栏 JSON；
- 拒绝缺字段、错误 `dedupe_key` 和缺来源链接；
- 第一次失败、第二次成功的重试路径；
- 两次失败后写入 failure 文件并更新状态；
- 成功后原子写入 final 并更新状态；
- 已成功选题不重复调用 Hermes；
- `build-queue` 不再选择发布队列中已有选题；
- 每日编排按顺序调用四个阶段，前置失败时不调用 Hermes。

服务器验收：

1. 本地测试全部通过；
2. 上传并安装新版本；
3. 将现有两条旧队列迁移为 `needs_generation`；
4. 真实调用 Hermes 生成两篇内容；
5. 验证 `out/final/` 有两份合法 JSON；
6. 验证数据库状态为 `needs_human_review`；
7. 安装并启用 systemd timer；
8. 验证下一次执行时间为北京时间次日 08:00。

## 运营边界

前 30 天继续人工审核。审核者从 `platform_markdown.wechat`、`xiaohongshu`、`toutiao`、`zhihu` 选择对应版本复制发布；发现标题与正文不一致、事实来源不足或平台风险提示时停止发布。
