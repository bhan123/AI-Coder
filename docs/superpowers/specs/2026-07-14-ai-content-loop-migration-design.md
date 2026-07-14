# AI Content Loop 独立迁移设计

## 目标

将 AI 内容自动化项目从 `D:\NR_Projects` 拆出，迁移为 `D:\AI_coder` 下唯一的、本地独立 Git 仓库。迁移完成后，`D:\NR_Projects` 不再保留该项目的可运行代码副本；腾讯云 Lighthouse 的运行目录和内容数据不改动。

## 已确认事实

- 最新可复现版本是提交 `12113ff`（`fix: restore reader-first editorial voice`）。
- `D:\NR_Projects\.worktrees\human-editorial-visuals-phase1` 存在与内容项目无关的工作树删除状态，不能把该目录当作普通文件夹直接复制。
- `D:\AI_coder` 中现有的是旧副本，缺失当前提示词和功能；其 `.git` 不是有效仓库。
- 当前最新工作树中没有需要迁移的本地 `data/`、`out/` 或密钥配置；Lighthouse 继续是线上运行数据的所在地。

## 决策

采用“从已提交快照构建临时独立仓库，再切换目录”的方式：

1. 从提交 `12113ff` 导出内容项目的受控文件集合，而不是复制工作树。
2. 在 `D:\AI_coder.__staging__` 初始化一个全新的独立 Git 仓库，并创建迁移提交，记录源提交号。
3. 在临时目录运行内容项目全量测试和结构检查。
4. 将旧 `D:\AI_coder` 临时改名为带时间戳的回滚目录，把通过验证的 staging 目录切换为正式目录。
5. 在正式目录再次运行测试并核对 Git 状态；失败时立刻恢复旧目录。
6. 验证成功后，删除临时旧目录，并只删除 `D:\NR_Projects` 中已迁出的内容项目路径与对应 worktree；不改动机器人数据等任何无关项目。

## 迁移范围

迁入独立仓库：

- `ai_content_loop/`
- `tests/ai_content_loop/`
- 内容项目所需的 `deploy/content-review/` 与 `deploy/systemd/`
- `docs/ai-content-loop/`，以及与 AI 内容项目直接相关的设计、实施计划
- 为独立项目裁剪后的 `.gitignore` 和项目说明文件

不迁入：

- `ITF_DATA/`、`MWV_*`、机器人数据、临时需求等无关目录
- `.pytest_cache`、`__pycache__`、临时测试目录
- `data/`、`out/`、日志、密钥和服务器运行产物

## 安全与回滚

- 在首次完整测试成功前，源提交、源工作树和旧 `D:\AI_coder` 都保留。
- 目录切换使用重命名，不使用覆盖式复制；任一切换后测试失败，恢复旧目录。
- 删除仅针对列出的项目路径，执行前逐个解析绝对路径并确认它们位于预期根目录。
- 服务端不迁移、不重启、不清理；本地新仓库验证通过后，后续部署才从 `D:\AI_coder` 发起。

## 验收标准

- `D:\AI_coder` 是有效 Git 仓库，默认分支为 `main`，包含最新提示词版本 `scoring-v6`、`factual-v8`、`editorial-v12`。
- 在 `D:\AI_coder` 运行 `tests\ai_content_loop` 全量通过。
- 新仓库的核心项目文件与 `12113ff` 导出内容哈希一致。
- Lighthouse 保持可访问，且没有因本地目录迁移发生变更。
- `D:\NR_Projects` 中不再存在本地可运行的 AI Content Loop 项目副本或关联 worktree。
