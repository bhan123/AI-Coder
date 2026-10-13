# WeChat 层叠三消小游戏

基于 **Cocos Creator 3.8.x** + **TypeScript** 的微信小游戏，采用"层叠式三消"玩法（3D 堆叠牌阵 + 槽位收集消除）。

> **用户目标**：上班族通勤时 2~5 分钟一局的轻量治愈游戏。
> **当前进度**：核心算法 + 游戏系统 + 美术风格 + 关卡生成器 + 视频复活 **全部完成**；L1~L20 共 20 关已就绪。
> **距离可上线还差**：编辑器侧场景搭建 + 美术资源产出 + 微信发布配置（appid / 真实广告位）+ L21~L50 关卡。
> **下一接手者该做什么**：按 `docs/scene-setup.md` 搭场景 + 按 `docs/art-style.md` 出图 + 把 `tools/level-params.csv` 扩到 L50 + 替换 `config.ts` 里占位广告位 id。

---

## 目录（Quick Links）

- [技术栈 & 环境要求](#技术栈--环境要求)
- [快速开始](#快速开始)
- [架构总览](#架构总览)
- [场景节点结构](#场景节点结构)
- [目录结构](#目录结构)
- [核心玩法机制](#核心玩法机制)
- [API 速查](#api-速查)
- [数据 Schema](#数据-schema)
- [事件目录](#事件目录)
- [约定与代码风格](#约定与代码风格)
- [美术风格（速览）](#美术风格速览)
- [关卡生成器](#关卡生成器)
- [CLI 命令](#cli-命令)
- [场景搭建 Checklist](#场景搭建-checklist)
- [已知问题与 TODO](#已知问题与-todo)
- [下一步开发计划](#下一步开发计划)
- [常见问题](#常见问题)

---

## 技术栈 & 环境要求

- **Cocos Creator 3.8.x**（2D 项目）
- **TypeScript 5.x**
- **微信开发者工具**（发布小游戏）
- **Node.js 16+**（仅用于跑关卡生成器）

---

## 快速开始

### 1. 打开工程

首次打开项目时 Cocos 会自动生成 `settings/`、`library/`、`temp/` 等本地目录（已加入 `.gitignore`）。

```
用 Cocos Dashboard → 打开其他项目 → 选本目录
```

### 2. 创建第一个场景

按下面的"**场景节点结构**"在 `Main.scene` 里搭建节点树，然后把脚本挂到对应节点上、把子节点引用拖到 `@property` 字段。**详细步骤**见 `docs/scene-setup.md`。

### 3. 创建 Tile 预制体

在 `assets/prefabs/` 右键 → 创建 → **预制体 (Prefab)**，命名为 `Tile`：
- 根节点：加 `UITransform`、`Sprite`、`Tile.ts`
- `Sprite.spriteFrame` 默认指向一张"占位色块"（后续换成真实图案）
- Inspector 字段绑定：
  - `Tile.patternFrames`：拖入 6 张主图案 SpriteFrame（按 enum 顺序）
  - `Tile.backFrame`：牌背 SpriteFrame
  - `Tile.highlightFrame`：高亮 SpriteFrame（可选）
  - `Tile.bombFrame`：炸弹图案 SpriteFrame
  - `Tile.wildFrame`：万能图案 SpriteFrame

### 4. 准备关卡数据

**20 份示例关卡已就绪**：`assets/resources/levels/level_001.json` ~ `level_020.json`。
- L1~L5：手写
- L6~L20：`tools/level-generator.ts` 自动生成（参数在 `tools/level-params.csv`）

L21~L50 待用生成器扩展（详见 `docs/level-editor.md`）。

### 5. 浏览器预览

编辑器右上角 ▶ 播放按钮 → 浏览器打开预览。

### 6. 真机预览（微信小游戏）

1. Cocos → **项目 → 构建发布** → 平台选「微信小游戏」
2. 配置 `appid`（测试可填"游客模式"）+ 初始场景 `Main`
3. 构建产物到 `build/wechatgame/`，用微信开发者工具导入预览

---

## 架构总览

### 模块依赖图

```
                    ┌──────────────┐
                    │   Main.ts    │  ← 场景入口（节点绑定 + 事件桥接）
                    └──────┬───────┘
                           │ 持有
        ┌─────────────┬────┴────┬─────────────┬─────────────┐
        ▼             ▼         ▼             ▼             ▼
   LevelManager  DialogCtrl  HUDCtrl   HintCtrl     (platform/WxApi)
        │             │         │             │
        │ 创建/注入   │         │             │
        ▼             ▼         ▼             ▼
  ┌──────────┐   ┌──────────┐  ┌─────────┐  ┌────────────┐
  │ MatchSys │   │ EventBus │  │PropSys  │  │  HintSys   │
  │  PropSys │   │ GameMgr  │  └────┬────┘  │  (在 Board │
  └────┬─────┘   │  AudioMgr│       │       │  + Tile 上 │
       │         └────┬─────┘       │       │   工作)     │
       ▼              │             │       └────────────┘
   ┌───────┐          │             ▼
   │ Board │ ←────────┴────────┐
   │  Tile │                   │
   └───────┘                   ▼
                         ┌──────────┐
                         │ Storage  │  ← localStorage 包装
                         └──────────┘
```

### 核心数据流

```
玩家点击 → boardHitArea.onTouchEnd
       → board.hitTest(worldPos)
       → matchSystem.onTap(tile)
       → board.isClickable / flyToSlot / findTriple / removeTriples
       → 触发事件（TileSelected / TileRemoved / LevelComplete / LevelFailed）
       → Main.ts 监听 → DialogController 弹窗 / 切关
       → 玩家在弹窗选操作 → Main.retry / goToNextLevel / rewardAdRescue
       → LevelManager.unloadLevel + startLevel + loadLevel
```

### 单例与生命周期

- `GameManager` / `AudioManager`：单例 + `director.addPersistRootNode` 跨场景常驻
- 其他（`MatchSystem` / `PropSystem`）：由 `LevelManager.buildLevel` 时 new，关卡切换时销毁重建
- `EventBus`：全局静态类，handler 在 `onDestroy` 统一 off

---

## 场景节点结构

```
Canvas (UITransform + Canvas, design resolution 750x1334)
├── GameManager        (空节点 + GameManager.ts)
├── AudioManager       (空节点 + AudioManager.ts)
│   └── AudioSource    (BGM 播放源)
├── BoardRoot          (空节点 + Board.ts)
│   └── Tiles          (空节点，绑定到 Board.tileContainer)
├── LevelManager       (空节点 + LevelManager.ts)
│   └── Inspector 引用：
│       - board        = BoardRoot 上的 Board 组件
│       - tileContainer = BoardRoot/Tiles
│       - tilePrefab   = assets/prefabs/Tile.prefab
├── HintController     (空节点 + HintController.ts)
├── HUD                (空节点 + HUDController.ts)
│   ├── ScoreLabel     (Label → HUDController.scoreLabel)
│   ├── LevelLabel     (Label → HUDController.levelLabel)
│   ├── UndoLabel      (Label → HUDController.undoLabel)
│   ├── PauseBtn       (Button → HUDController.pauseBtn)
│   ├── UndoBtn        (Button → HUDController.undoBtn)
│   ├── UndoCountLabel (Label → HUDController.undoCountLabel)
│   ├── ShuffleBtn     (Button → HUDController.shuffleBtn)
│   ├── ShuffleCountLabel (Label)
│   ├── RemoveBtn      (Button → HUDController.removeBtn)
│   └── RemoveCountLabel (Label)
├── DialogController   (空节点 + DialogController.ts)
│   ├── LevelCompleteDialog (Node, 默认 active=false)
│   │   ├── CompleteLevelLabel  (Label)
│   │   ├── CompleteScoreLabel  (Label)
│   │   ├── NextBtn             (Button)
│   │   ├── ShareBtn            (Button)
│   │   └── CompleteCloseBtn    (Button, X 关闭 = Next)
│   ├── LevelFailedDialog (Node, 默认 active=false)
│   │   ├── FailedLevelLabel    (Label)
│   │   ├── FailedScoreLabel    (Label)
│   │   ├── RetryBtn            (Button)
│   │   ├── ShareRescueBtn      (Button)
│   │   ├── RewardAdBtn         (Button, "看视频复活"，主色按钮)
│   │   └── FailedCloseBtn      (Button, X 关闭只 hide)
│   └── PauseDialog (Node, 默认 active=false)
│       ├── ResumeBtn         (Button)
│       ├── PauseRetryBtn     (Button)
│       └── PauseCloseBtn     (Button, X 关闭 = Resume)
├── Background         (Sprite, 背景图)
└── Main               (空节点 + Main.ts)
    └── Inspector 引用：
        - gameManagerNode = GameManager 节点
        - audioManagerNode = AudioManager 节点
        - board = BoardRoot 上的 Board
        - levelManager = LevelManager 节点
        - hud = HUD 节点
        - hintController = HintController 节点
        - dialog = DialogController 节点
        - boardHitArea = BoardRoot 节点（接收点击）
```

每个 Dialog 内部建议加一个全屏 `BlockInputEvents` 子节点 + 半透明黑色 Sprite 作为遮罩。

---

## 目录结构

```
wechat-match3/
├── assets/
│   ├── scenes/                # Main.scene（编辑器创建）
│   ├── prefabs/               # Tile.prefab（编辑器创建）
│   ├── scripts/
│   │   ├── config.ts              # WxConfig (广告位 + 分享文案) + LevelConfig
│   │   ├── Main.ts                # 场景入口，接 Dialog / Hint / 视频复活
│   │   ├── core/                  # 全局基础设施
│   │   │   ├── GameManager.ts     # 单例 + 状态机 + 分数/关卡/道具/提示/视频复活次数
│   │   │   ├── EventBus.ts        # 解耦事件总线 + GameEvent 常量
│   │   │   ├── AudioManager.ts    # BGM + SFX（含 SfxName 枚举）
│   │   │   └── Storage.ts         # localStorage 持久化
│   │   ├── game/                  # 游戏核心
│   │   │   ├── Board.ts           # 3D 牌堆 + 可点击判定 + hitTest
│   │   │   ├── Tile.ts            # 牌视图/状态/消除动画 + special 字段
│   │   │   ├── MatchSystem.ts     # 槽位 + 三消 + bomb 提前引爆 + 撤销 + forceClearSlot
│   │   │   ├── LevelManager.ts    # 关卡 JSON 加载 + 校验 + 卸载
│   │   │   ├── PropSystem.ts      # 撤销/洗牌/移出（含 shuffle 算法）
│   │   │   └── HintController.ts  # 长按高亮可点击牌
│   │   ├── ui/
│   │   │   ├── HUDController.ts   # 分数/撤销/暂停 + 道具按钮 + 计数
│   │   │   └── DialogController.ts # 通关/失败/暂停弹窗（含视频复活按钮）
│   │   └── platform/
│   │       └── WxApi.ts           # 微信能力封装（含 showRewardedAd）
│   ├── resources/
│   │   └── levels/            # 关卡 JSON（L1~L20 共 20 关已就绪）
│   ├── art/{ui,tiles,fx,bg}/  # 美术资源
│   └── audio/                 # BGM + SFX
├── docs/
│   ├── art-style.md           # 美术风格定调（配色 + ASCII 布局）
│   ├── level-editor.md        # 关卡批量产出工作流 + 设计方案
│   └── scene-setup.md         # Main.scene 节点搭建 Checklist（43 个 @property）
├── tools/
│   ├── level-generator.ts     # 关卡生成器 CLI（已实现 + 已跑通 L6~L20）
│   └── level-params.csv       # L6~L20 参数表（CSV 驱动生成器）
├── package.json
├── tsconfig.json
└── README.md                  # 本文档
```

---

## 核心玩法机制

### 1. 3D 牌阵

每张牌在 `(gx, gy, gz)` 网格上占一格。`gz` 越大视觉越在上层。

### 2. 可点击判定（`Board.isClickable`）

一张牌可点击当且仅当：
1. 未被消除
2. 正上方 `(gx, gy, gz+1)` 没有未消除的牌
3. 同区域更高 z 的牌不在屏幕空间覆盖它（避免 z=2 但偏右下的牌挡住 z=1）

### 3. 三消（`MatchSystem.findTriple`）

槽位里凑齐 3 张同 `pattern` 的牌 → 消除：
- 全 normal：按 pattern 分组，数量 ≥ 3 触发
- 含 wild：wild 可替补任意 pattern，只要 `normal + wild ≥ 3`
- 含 bomb：消除场上所有同 pattern 的 normal 牌（连锁）

### 4. Bomb 触发策略（三档）

| 档 | 触发条件 | 路径 |
|---|---|---|
| 普通 | `slot.length < slotCapacity - 1` 时 tap bomb | bomb 入 slot，等凑齐 3 消时随 slot 消除（**已被提前引爆短路**） |
| 提前引爆 | `slot.length ≥ slotCapacity - 1` 时 tap bomb | **不入 slot**，直接 `detonateBombImmediate` 触发场上同 pattern 连锁消除 + 加 50 bomb 奖励分 |
| 孤 bomb | slot 里只剩 bomb 时（隐式） | 由"提前引爆"条件自动覆盖 |

加分规则：普通 3 消 `cascade.length * 10`，bomb 触发额外 +50。

### 5. Shuffle 算法（`PropSystem.shuffle`）

1. 收集场上 normal / special 牌；special 牌保持原 `(gx, gy, gz)` 不动
2. 候选池：6 × 8 × 4 = 192 格（保守覆盖所有当前关卡）
3. Fisher-Yates 洗候选池
4. 给 normal 牌分配不冲突的坐标
5. **可行性检测**：`isLayoutViable` 判定至少有一个 pattern ≥ 3 且其中至少一张 gz 是该 pattern 中最大值（保证可点击）
6. **最多重试 5 次**，仍不可行 → `GameManager.refundProp('shuffle')` 退还道具次数
7. 提交新坐标 + Tween 0.3s 线性动画到新位置

复杂度：典型关卡 n ≤ 60，单次重试 < 1ms，5 次重试总和可忽略。

### 6. 关卡切换流程

- **通关**：`GameEvent.LevelComplete` → `DialogController.showLevelComplete` → 玩家点 [下一关] → `Main.goToNextLevel` → `unloadLevel + startLevel + loadLevel`
- **失败**：`GameEvent.LevelFailed` → `DialogController.showLevelFailed` → 玩家选 [重试] / [分享复活] / [看视频复活]
- **暂停**：HUD 点暂停 → `GameManager.togglePause` → `GameEvent.PauseToggled(true)` → `DialogController.showPause` → [继续] 恢复 / [重玩本关] 重置
- **重试**：`Main.retry` = `dialog.hideAll + unloadLevel + startLevel(current) + loadLevel(current)`

### 7. 视频复活（`WxApi.showRewardedAd`）

失败弹窗里的"看视频复活"按钮接激励视频广告。三条路径：

| 路径 | 触发 | 行为 |
|---|---|---|
| A 成功 | 看完整广告 + `rescueCount < maxRescuePerLevel` + `state == GameOver` | `GameManager.rescueFromAd` 切回 `Playing` + `MatchSystem.forceClearSlot` 把 slot 牌 Tween 回原位 + `rescueCount++` |
| B 中途关闭 | `showRewardedAd` 返回 false | emit `AdRescueFailed` + 重新 `showLevelFailed`（可再试） |
| C 已用完 | `rescueCount >= maxRescuePerLevel` | 跳过广告，直接 `retry` 重置关卡 |

广告位 id 配置在 `assets/scripts/config.ts` 的 `WxConfig.rewardAdUnitId`，部署时替换为微信公众平台申请的真实 id。编辑器环境下 `WxApi.showRewardedAd` 自动 `resolve(false)`，走路径 B 不会卡死。

限制：`maxRescuePerLevel = 1`（防止刷广告），可通过 `LevelConfig.maxRescuePerLevel` 调整。

---

## API 速查

> 接手者最常用的入口。完整签名看各文件源码。

### `GameManager`（单例，全局状态）

```typescript
import { GameManager, GameState, PropType, PropCounts } from './core/GameManager';

GameManager.instance.state              // 当前状态（'playing' | 'paused' | 'gameover' | 'levelcomplete' | 'idle'）
GameManager.instance.score              // 当前分数
GameManager.instance.currentLevel       // 当前关卡 ID
GameManager.instance.undoCount          // 剩余撤销次数
GameManager.instance.hintCount          // 剩余提示次数
GameManager.instance.propCounts         // { undo, shuffle, remove } 剩余
GameManager.instance.rescueCount        // 当前关已用视频复活次数

GameManager.instance.startLevel(id)     // 开始新关，重置分数/次数
GameManager.instance.addScore(delta)    // 加分 + 更新最佳分
GameManager.instance.completeLevel()    // 通关 + 解锁下一关 + emit
GameManager.instance.failLevel()        // 失败 + emit LevelFailed
GameManager.instance.togglePause()      // 切换暂停 + director.pause/resume
GameManager.instance.useHint()          // 扣 1 次提示 + emit（返回 boolean）
GameManager.instance.useProp(type)      // 扣 1 次道具（type: 'undo'|'shuffle'|'remove'）
GameManager.instance.refundProp(type)   // 退还 1 次道具（shuffle 失败时用）
GameManager.instance.rescueFromAd()     // 视频复活（state=GameOver 时才能成功）
```

### `MatchSystem`（由 LevelManager 创建）

```typescript
matchSystem.onTap(tile)            // 玩家点击牌的主入口
matchSystem.undoLast()             // 撤销最后入 slot 的牌（返回 boolean）
matchSystem.forceClearSlot()       // 视频复活时清空 slot（不触发失败）
matchSystem.reset()                // 重置 slot（关卡切换时）
matchSystem.slotSnapshot           // 只读：当前 slot 里的牌
```

### `Board`（挂在 BoardRoot 节点）

```typescript
board.addTile({ id, pattern, gx, gy, gz, node, special? })  // 注册一张牌
board.isClickable(tile)            // 判定可点击
board.hitTest(worldPos)            // 点 → 命中的最上层牌
board.findAllByPattern(pattern)    // 场上所有同 pattern 未消除的 normal 牌（bomb 连锁用）
board.forEachActive(cb)            // 遍历所有未消除的牌
board.isCleared()                  // 场上无牌
board.releaseTileNode(node)        // 消除动画完成后回收节点
```

### `PropSystem`（由 LevelManager 创建）

```typescript
propSystem.useProp(type)           // 入口：扣次数 + 执行效果（type: 'undo'|'shuffle'|'remove'）
propSystem.updateGeometry(geo)     // 关卡切换后刷新几何参数
```

### `DialogController`（挂在 DialogController 节点）

```typescript
dialog.showLevelComplete(id, score, onNext, onShare)
dialog.showLevelFailed(id, score, onRetry, onShareRescue, onRewardAd)
dialog.showPause(onResume, onRetry)
dialog.hideAll()
```

### `WxApi`（平台能力，无副作用封装）

```typescript
WxApi.isInMiniGame()               // 是否在微信小游戏环境
WxApi.showShareMenu()
WxApi.shareAppMessage({ title, imageUrl, query })
WxApi.vibrateShort('light'|'medium'|'heavy')
WxApi.vibrateLong()
WxApi.createBannerAd(adUnitId, style?)   // 返回 ad 实例
WxApi.showRewardedAd(adUnitId)           // Promise<boolean>，看完 = true
WxApi.getSystemInfo()                    // { screenWidth, screenHeight, pixelRatio, platform }
```

### `HintController`（挂在 HintController 节点）

挂在节点上后绑定 `boardHitArea`，自动监听长按 0.5s 触发高亮。

### `EventBus`（静态）

```typescript
import { EventBus, GameEvent } from './core/EventBus';
EventBus.on(event, handler, this)
EventBus.off(event, handler, this)
EventBus.emit(event, ...args)
```

---

## 数据 Schema

### `LevelJson`（关卡 JSON）

```typescript
interface LevelJson {
    levelId: number;          // 关卡 ID（== 文件名中的数字）
    slotCapacity: number;     // 槽位上限（默认 7）
    cellWidth: number;        // 牌宽（默认 80）
    cellHeight: number;       // 牌高（默认 80）
    layerOffset: number;      // 每层 Y 偏移（默认 30，堆叠视觉效果）
    origin: { x: number; y: number };  // 网格原点（世界坐标）
    tiles: Array<{
        pattern: number;      // 0..N 图案 ID
        gx: number; gy: number; gz: number;  // 网格坐标
        special?: 'none' | 'bomb' | 'wild'; // 默认 'none'
    }>;
}
```

**约束**：
- `tiles.length` 是 3 的倍数
- 每个 `pattern` 的 normal 牌数是 3 的倍数
- `gz` 从 0 起连续到 `layerCount - 1`
- `validateLevel()` 只 warn 不阻塞

### `TileData`（运行时牌数据）

```typescript
interface TileData {
    id: number;
    pattern: number;
    gx: number; gy: number; gz: number;
    node: Node;
    removed: boolean;
    special: 'none' | 'bomb' | 'wild';
}
```

### `WxConfig`（`assets/scripts/config.ts`）

```typescript
WxConfig.rewardAdUnitId     // 激励视频广告位 id（部署时替换）
WxConfig.bannerAdUnitId     // Banner 广告位 id（预留）
WxConfig.shareWinTitle      // 通关分享文案
WxConfig.shareRescueTitle   // 失败分享复活文案
```

### `LevelConfig`（`assets/scripts/config.ts`）

```typescript
LevelConfig.startLevel          // 起始关卡（debug 时改）
LevelConfig.maxRescuePerLevel   // 每关最多视频复活次数（防刷广告）
```

### `PropCounts`（`GameManager`）

```typescript
{ undo: number; shuffle: number; remove: number; }
```

### 关卡生成器参数（`LevelGenParams`）

```typescript
{
    levelId: number;
    totalTiles: number;      // 含 bomb + wild
    patternCount: number;    // 主图案种类
    layerCount: number;      // z 层数（1~6）
    bombCount: number;
    wildCount: number;
    density: number;         // 0..1，堆叠密度
    slotCapacity: number;
}
```

---

## 事件目录

`assets/scripts/core/EventBus.ts` 里的 `GameEvent` 常量：

| 常量 | 字符串 | 触发时机 | 参数 |
|---|---|---|---|
| `TileSelected` | `tile.selected` | 牌进 slot | `(tile, slotLength)` |
| `TileRemoved` | `tile.removed` | 牌触发消除动画 | `(tiles[])` |
| `SlotFull` | `slot.full` | slot 满（已废弃，失败用 LevelFailed） | — |
| `LevelComplete` | `level.complete` | 通关 | `(levelId, score)` |
| `LevelFailed` | `level.failed` | 失败 | `(levelId, score)` |
| `ScoreChanged` | `score.changed` | 分数变化 | `(score)` |
| `UndoCountChanged` | `undo.changed` | 撤销次数变化 | `(count)` |
| `PauseToggled` | `pause.toggled` | 暂停切换 | `(paused: boolean)` |
| `HintCountChanged` | `hint.changed` | 提示次数变化 | `(count)` |
| `PropCountChanged` | `prop.changed` | 道具次数变化 | `(PropCounts)` |
| `BombDetonated` | `bomb.detonated` | bomb 提前引爆 | `(bombTile, cascadeSize)` |
| `DialogShow` | `dialog.show` | 弹窗显示 | `(type: string)` |
| `DialogHide` | `dialog.hide` | 弹窗隐藏 | — |
| `AdRescue` | `ad.rescue` | 视频复活成功 | `(rescueCount)` |
| `AdRescueFailed` | `ad.rescue.failed` | 视频复活失败/取消 | — |

---

## 约定与代码风格

### TypeScript / Cocos 3.x

- **类装饰器**：`@ccclass('ClassName')` + 字段 `@property(Type)`
- **引擎导入**：`import { _decorator, Component, Node, ... } from 'cc'`
- **单例**：`GameManager.instance` / `AudioManager.instance`
- **跨模块通信**：`EventBus.emit / on / off`（不直接互相 import）
- **场景生命周期**：`onLoad` / `start` / `onDestroy`（事件订阅在 onDestroy 必须 off）
- **节点事件**：`node.on(Node.EventType.TOUCH_END, handler, this)`；按钮用 `Button.EventType.CLICK`
- **Tween**：`Tween.stopAllByTarget(node) + Tween.get(node).to(...).start()`（重要：先 stop 再启动避免串扰）
- **类型**：`strict: false`（Cocos 默认），`experimentalDecorators: true`

### 文件组织

- 业务逻辑放 `game/`，UI 放 `ui/`，全局基础设施放 `core/`，平台能力放 `platform/`
- 场景入口固定在 `assets/scripts/Main.ts`
- 配置常量放 `assets/scripts/config.ts`（不要硬编码在多个文件里）

### 注释原则

- **不写 WHAT**（命名已经说明）
- **只写 WHY**（为什么这么做、不这么做会怎样）
- 防御性代码 / 边界 case 处理要简短标注

### 命名

- 类名 PascalCase：`MatchSystem`
- 枚举值用字符串 enum 而不是数字（避免重构时断链）
- 私有字段 `_` 前缀（如 `_instance`）
- 事件名常量统一在 `GameEvent`

---

## 美术风格（速览）

**推荐方向**：糖果色萌系 — 高饱和撞色 + 圆润厚边图标 + 弹性缓动。

**主色板**：

| 用途 | hex |
|---|---|
| 主色（按钮/强调）蜜桃粉 | `#FF6B8B` |
| 辅助色 鹅黄 | `#FFD166` |
| 背景色 奶粉色 | `#FFF4F0` |
| 通关高亮 薄荷绿 | `#7AE0B5` |
| 失败警示 番茄红 | `#FF5A5A` |

完整 ASCII 布局示意（6 个主屏幕）+ 牌面图案设计 + 字号层级 + 素材采购清单见 `docs/art-style.md`。

---

## 关卡生成器

**已实现**：`tools/level-generator.ts`（约 530 行，TypeScript CLI 工具）。

**已生成的关卡**：L6~L20 共 15 关，参数在 `tools/level-params.csv`：

| Lvl | total | pat | bomb | wild | normal | layers | density |
|-----|-------|-----|------|------|--------|--------|---------|
| 6   | 24    | 4   | 0    | 0    | 24     | 2      | 0.55    |
| 7   | 30    | 5   | 0    | 0    | 30     | 2      | 0.60    |
| 8   | 27    | 3   | 0    | 3    | 24     | 2      | 0.60    |  ← 引入 wild
| 9   | 36    | 4   | 0    | 0    | 36     | 3      | 0.65    |
| 10  | 39    | 3   | 0    | 0    | 39     | 3      | 0.65    |
| 11  | 45    | 5   | 3    | 0    | 42     | 3      | 0.70    |  ← 引入 bomb
| 12  | 48    | 4   | 3    | 0    | 45     | 3      | 0.70    |
| 13  | 54    | 6   | 0    | 3    | 51     | 3      | 0.75    |
| 14  | 60    | 5   | 3    | 3    | 54     | 4      | 0.75    |
| 15  | 57    | 3   | 3    | 3    | 51     | 4      | 0.80    |
| 16  | 66    | 6   | 3    | 3    | 60     | 4      | 0.80    |
| 17  | 72    | 6   | 6    | 0    | 66     | 4      | 0.80    |
| 18  | 75    | 5   | 6    | 3    | 66     | 4      | 0.85    |
| 19  | 81    | 3   | 9    | 3    | 69     | 5      | 0.85    |
| 20  | 90    | 6   | 9    | 3    | 78     | 5      | 0.90    |

**L21~L50**：在 `tools/level-params.csv` 追加行 + 重新跑生成器即可。

完整方案对比 + 接口设计 + 工作流见 `docs/level-editor.md`。

---

## CLI 命令

```bash
# 安装依赖（首次）
cd wechat-match3
npm install

# 批量生成 L6~L20（写到默认目录 assets/resources/levels/）
npx tsx tools/level-generator.ts --range 6-20 --write

# 读 CSV 参数表生成
npx tsx tools/level-generator.ts --csv tools/level-params.csv --write

# 单关复现（stdout 输出 JSON，可重定向到任意路径）
npx tsx tools/level-generator.ts --levelId 6 --seed 42

# 自定义输出目录
npx tsx tools/level-generator.ts --range 6-20 --write --outDir /tmp/levels

# 可选参数
#   --seed N        随机种子（默认 42，相同 seed 产出相同关卡）
```

**生成器函数**（在 `tools/level-generator.ts` 里）：

```typescript
function generateLevel(params: LevelGenParams, seed?: number): LevelJson
function generateBatch(params: LevelGenParams[], seed?: number): LevelJson[]
function loadParamsFromCsv(path: string): LevelGenParams[]
function validateLevelSpec(level: LevelJson): { ok: boolean; warnings: string[] }
```

---

## 场景搭建 Checklist

`docs/scene-setup.md` 提供了**完整**的 `Main.scene` 搭建指南：

- **43 个 @property** 全部列出（Main 8 / Dialog 16 / HUD 10 / Board 2 / LevelManager 3 / HintController 2 / AudioManager 2）
- **13 个 Label 节点初始 string** 速查表
- **3 个 Dialog 内部子节点结构**（含遮罩、卡片、按钮）
- **17 项验证清单**（按场景启动顺序）
- **8 个常见搭建错误**（拖错引用 / Dialog active 未关 / Design Resolution / SpriteFrame / JSON 路径 / UITransform / 字体 / Button Transition）

按文档 checklist 顺序执行即可完成场景搭建。

---

## 已知问题与 TODO

> 接手者从这开始往下做最有效。

### 必须做（阻塞上线）

- [ ] **场景搭建**：按 `docs/scene-setup.md` 在 Cocos 编辑器里搭 `Main.scene`（43 个 @property 拖一遍）
- [ ] **Tile 预制体**：制作 6 种主图案 + 牌背 + 高亮 + 炸弹 + 万能 = 10 张 SpriteFrame
- [ ] **真实广告位**：替换 `assets/scripts/config.ts` 的 `WxConfig.rewardAdUnitId` 为真实 id
- [ ] **微信 appid**：在 Cocos 构建发布面板填入

### 应该做（影响体验）

- [ ] **L21~L50**：在 `tools/level-params.csv` 追加 30 行 + 跑生成器
- [ ] **关卡选择界面**：目前是直接 `startLevel(1)`，需要主菜单 + 选关 + 解锁状态
- [ ] **美术资源产出**：按 `docs/art-style.md` 出图（牌面/UI 套图/背景）
- [ ] **BGM + 8 个 SFX** 录入（`click` / `match` / `add_to_slot` / `slot_full` / `win` / `lose` / `undo` / `hint`）

### 后续可做（锦上添花）

- [ ] **Banner 广告**：在主菜单 / 暂停界面挂 `WxApi.createBannerAd`
- [ ] **分享回调校验**：`shareRescue` 当前是无条件 `retry`，未接 `onShow` 验证
- [ ] **首屏分包加载**：主包 ≤ 4MB 限制下，把关卡 JSON 拆到子包
- [ ] **好友排行榜**：用微信开放数据域渲染
- [ ] **关卡编辑器 UI**：当前只能用 CSV + 生成器；BOSS 关（建议 L41~L50）建议做可视化编辑器
- [ ] **i18n**：所有 Label.string 抽出到 i18n 表
- [ ] **埋点**：通关率 / 复活率 / 道具使用率 / 关卡失败点

### 已知 BUG / 限制

- **shuffle 候选池硬编码**（6×8×4 = 192 格）：关卡牌数 > 192 时会退款
- **Board.grid key 不更新**：shuffle 后只改 `tile.gx/gy/gz` 不改 grid 的 key（语义不变但有副作用）
- **节点池未实现**：`unloadLevel` 后节点未还池，下次 instantiate 浪费
- **Dialog X 按钮行为不对称**：`completeCloseBtn = Next` / `failedCloseBtn = 只 hide` / `pauseCloseBtn = Resume`，如需统一可改
- **shareRescue 无校验**：分享后无条件 retry，没有验证 `shareTicket`
- **`forceClearSlot` 不 emit 任何事件**：UI 层无感知，slot 飞回原位 Tween 不会触发分数变化

---

## 下一步开发计划

| 阶段 | 状态 | 说明 |
|------|------|------|
| 项目脚手架 | ✅ 完成 | 目录、核心脚本、构建配置 |
| 核心玩法联调 | ✅ 完成 | Board + Tile + MatchSystem + 关卡 + 5 份示例 |
| 特殊牌系统 | ✅ 完成 | bomb 提前引爆 + wild 替补 + 连锁消除 |
| 道具系统 | ✅ 完成 | 撤销/洗牌/移出 + 完整算法 |
| Hint 系统 | ✅ 完成 | 长按 0.5s 高亮可点击牌 |
| 弹窗系统 | ✅ 完成 | 通关/失败/暂停 + 按钮回调 |
| 视频复活 | ✅ 完成 | WxApi.showRewardedAd → rescueFromAd + forceClearSlot，三条路径处理 |
| 美术风格定调 | ✅ 完成 | 配色 + 6 屏 ASCII + 采购清单 |
| 关卡生成规划 | ✅ 完成 | C+D 组合方案 + CSV + 生成器设计 |
| 关卡生成器实现 | ✅ 完成 | tools/level-generator.ts + L6~L20 已生成 |
| 场景搭建 Checklist | ✅ 完成 | docs/scene-setup.md（43 个 @property + 17 项验证） |
| 场景搭建（编辑器） | ⬜ 下一步 | 按 scene-setup.md 在 Cocos 里搭 Main.scene + Tile.prefab + Dialog 节点 |
| 美术资源产出 | ⬜ | 牌面 6+ 种、UI 套图、背景、BGM + SFX |
| 关卡 L21~L50 | ⬜ | 在 level-params.csv 追加 + 跑生成器 |
| 微信发布配置 | ⬜ | appid、备案、首屏分包、WxConfig.rewardAdUnitId 替换真实 id |
| 上线测试 | ⬜ | 多机型真机 + 数值曲线调优 |

---

## 常见问题

**Q: 打开项目时编辑器报错？**
A: 删掉 `library/` `temp/` `local/` `settings/` 后重新打开，让 Cocos 重新生成。

**Q: 微信开发者工具预览黑屏？**
A: 检查 `Main.scene` 是否设为初始场景；检查控制台首屏错误（通常是脚本编译失败）。

**Q: 如何调试？**
A: Cocos 编辑器里直接 ▶ 播放即可断点调试；微信侧用微信开发者工具自带的调试器。

**Q: 关卡跑不通？**
A: 检查关卡 JSON：`totalTiles % 3 === 0`、每个 pattern 的 normal 牌数 `% 3 === 0`；`validateLevel` 会 warn 但不阻塞。

**Q: shuffle 卡死 / 退款？**
A: 5 次重试均不可行 → 触发退款。常见原因是场上牌数太多超过候选池（>192），需调整关卡参数或扩展 `PropSystem` 候选池范围。

**Q: 视频复活没反应？**
A: 检查 `assets/scripts/config.ts` 的 `WxConfig.rewardAdUnitId` 是否替换为真实广告位 id（默认是占位 `adunit-reward-placeholder`）。编辑器环境下无广告，会自动 `resolve(false)` 走"重新显示弹窗"路径，不会卡死。

**Q: 新加的脚本没生效？**
A: 1) 检查是否在 `Main.ts` 的 `@property` 列表里挂载；2) 检查 `onLoad` 里是否调用 `super.xxx`（Cocos Component 不会自动调用）；3) 控制台看编译错误。

**Q: 怎么新增一种 special 牌？**
A: 1) 改 `TileSpecial` 类型（`Tile.ts`）；2) 改 `Tile.refresh()` 加新分支；3) 改 `MatchSystem.findTriple / removeTriples` 加新规则；4) 改关卡 JSON schema 兼容；5) 改 `validateLevel`（`LevelManager.ts`）接受新值。
