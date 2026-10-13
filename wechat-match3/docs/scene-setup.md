# Main.scene 搭建 Checklist

> 一份能让人照着搭场景的 step-by-step 指南。所有节点命名、@property、初始 string 值与 README 严格对齐。

---

## 1. 前置准备

### 1.1 安装确认
- Cocos Creator **3.8.x** 已安装并打开 Dashboard
- 微信开发者工具（可选，仅真机预览时需要）
- Node.js 16+

### 1.2 打开项目
- Cocos Dashboard → **打开其他项目** → 选 `D:\AI_coder\wechat-match3\`
- 首次打开会自动生成 `settings/`、`library/`、`temp/`（已 `.gitignore`）

### 1.3 资源导入（按需）
> MVP 阶段美术均为占位，可先跳过；正式版按下面导入。

| 类别 | 目标目录 | 推荐格式 |
|------|---------|---------|
| 背景图 | `assets/art/bg/` | `.png` / `.jpg`，建议 750x1334 |
| 牌面 6+1+1 图案 | `assets/art/tiles/` | `.png`，每张 160x160（含边距） |
| 按钮 3 态 sprite | `assets/art/ui/btn/` | 9-slice `.png`（normal/pressed/disabled 三份） |
| 字体 | `assets/art/font/` | `.ttf`（思源黑体 / 站酷高端黑） |
| AudioClip BGM | `assets/audio/bgm/` | `.mp3` |
| AudioClip SFX | `assets/audio/sfx/` | `.mp3`，**文件名 = SfxName 值**（如 `click.mp3`） |

**导入流程**：把文件直接拖到 Project 面板对应目录 → Cocos 自动识别（纹理、字体、音频各走对应 importer）。

---

## 2. 创建场景

### 2.1 新建场景文件
1. 菜单 **File → New Scene → Empty**
2. **File → Save As** → `assets/scenes/Main.scene`
3. **Project → Project Settings → Project Data → Initial Scene** 选 `Main`

### 2.2 Canvas 设置
选中 Canvas 节点，Inspector 配置：

| 字段 | 值 |
|------|---|
| Design Resolution | **750 × 1334** |
| Fit Width | **关闭** |
| Fit Height | **开启** |
| Background Color | `#FFF4F0`（奶粉色，art-style.md §2） |

---

## 3. 节点树总览

```
Canvas (UITransform + Canvas, 750x1334)
├── Background              (Sprite, 背景图)
├── GameManager             (+ GameManager.ts)
├── AudioManager            (+ AudioManager.ts)
│   └── AudioSource         (BGM 源；AudioSourceComponent)
├── BoardRoot               (+ Board.ts)
│   └── Tiles               (Node, 绑定到 Board.tileContainer)
├── LevelManager            (+ LevelManager.ts)
├── HintController          (+ HintController.ts)
├── HUD                     (+ HUDController.ts)
│   ├── ScoreLabel          (Label)
│   ├── LevelLabel          (Label)
│   ├── UndoLabel           (Label)
│   ├── PauseBtn            (Button)
│   ├── UndoBtn             (Button)
│   ├── UndoCountLabel      (Label)
│   ├── ShuffleBtn          (Button)
│   ├── ShuffleCountLabel   (Label)
│   ├── RemoveBtn           (Button)
│   └── RemoveCountLabel    (Label)
├── DialogController        (+ DialogController.ts)
│   ├── LevelCompleteDialog (Node, active=false)
│   │   ├── Mask            (Sprite 半透黑 + BlockInputEvents)
│   │   ├── Card            (Sprite 白底圆角)
│   │   ├── TitleLabel      (Label "通关！")
│   │   ├── CompleteLevelLabel  (Label, 运行时填)
│   │   ├── CompleteScoreLabel  (Label, 运行时填)
│   │   ├── NextBtn         (Button 主色)
│   │   ├── ShareBtn        (Button 辅助色)
│   │   └── CompleteCloseBtn    (Button X 关闭)
│   ├── LevelFailedDialog   (Node, active=false)
│   │   ├── Mask
│   │   ├── Card
│   │   ├── TitleLabel      ("差一点点")
│   │   ├── FailedLevelLabel    (Label, 运行时填)
│   │   ├── FailedScoreLabel    (Label, 运行时填)
│   │   ├── RetryBtn           (Button 警示色)
│   │   ├── ShareRescueBtn     (Button 辅助色)
│   │   └── FailedCloseBtn     (Button X)
│   └── PauseDialog         (Node, active=false)
│       ├── Mask
│       ├── Card
│       ├── TitleLabel      ("暂停中")
│       ├── ResumeBtn       (Button 主色)
│       ├── PauseRetryBtn   (Button 辅助色)
│       └── PauseCloseBtn   (Button X)
└── Main                    (+ Main.ts)
```

---

## 4. 节点详细配置

### 4.1 Background
- **类型**：Node (UI 节点) + Sprite 组件
- **位置**：`(0, 0, 0)` 锚点 `(0.5, 0.5)`
- **UITransform contentSize**：`750 × 1334`
- **Sprite.spriteFrame**：拖入背景图（art-style.md §3.1 奶粉色 + 斜纹）
- **备注**：位于节点树**最底层**，避免遮挡牌阵

### 4.2 GameManager
- **类型**：Node + GameManager.ts 组件
- **位置**：任意（脚本里用 `director.addPersistRootNode` 设为常驻）
- **@property**：无
- **子节点**：无
- **备注**：Main.ts 会在 `start()` 里检查 `getComponent(GameManager)`，未挂时自动 `addComponent`

### 4.3 AudioManager
- **类型**：Node + AudioManager.ts + AudioSourceComponent（BGM）
- **@property**：
  - `bgm` (AudioClip) — 拖入 BGM `.mp3`
  - `sfxClips` (AudioClip[]) — 拖入 SFX 数组；**文件名必须等于 SfxName 字符串**（`click` / `match` / `add_to_slot` / `slot_full` / `win` / `lose` / `undo` / `hint`）
- **子节点 AudioSource**：本节点上加 AudioSourceComponent（脚本会在 onLoad 里 addComponent）
- **备注**：Main.ts 同样容错 addComponent

### 4.4 BoardRoot
- **类型**：Node + Board.ts 组件
- **位置**：屏幕中部 `(0, 50, 0)`，UITransform contentSize `(750, 700)`
- **@property**：
  - `tileContainer` — 拖入子节点 `Tiles`
  - `tilePool` (Node[]) — 留空（运行时由 LevelManager populate；MVP 可预实例化 9 个 Tile 节点拖入）
- **子节点 Tiles**：
  - 锚点 `(0.5, 0.5)`，位置 `(0, 0, 0)`，contentSize `(600, 600)`
  - 不需要 Sprite，纯空 Node 容器
- **验证**：编辑器里能看到 Tiles 节点占位（Hierarchy 显示蓝色节点图标）

### 4.5 LevelManager
- **类型**：Node + LevelManager.ts
- **位置**：任意（逻辑节点）
- **@property**：
  - `board` (Board) — 从 Project 或 Hierarchy 拖入 `BoardRoot` 上的 Board 组件
  - `tileContainer` (Node) — 拖入 `BoardRoot/Tiles`
  - `tilePrefab` (Prefab) — 从 Project 拖入 `assets/prefabs/Tile.prefab`
- **验证**：Inspector 三项都不为空；tilePrefab 拖入后会显示预制体引用图标

### 4.6 HintController
- **类型**：Node + HintController.ts
- **@property**：
  - `boardHitArea` (Node) — 拖入 `BoardRoot`（接收长按）
  - `board` (Board) — 拖入 `BoardRoot` 上的 Board 组件
- **备注**：逻辑节点，位置任意

### 4.7 HUD（重点）

位置均以 Canvas 中心 `(0,0)` 为基准，向上为 +Y。锚点 `(0.5, 0.5)`。

#### 顶部信息栏
| 子节点 | 类型 | 位置 (x, y) | contentSize | 字体 | 初始 string | 颜色 |
|--------|------|-------------|-------------|------|-------------|------|
| ScoreLabel | Label | `(0, 600)` | `(300, 50)` | 思源黑体 24pt | `"0"` | `#4A2E3A` |
| LevelLabel | Label | `(-280, 600)` | `(200, 50)` | 思源黑体 24pt | `"第 1 关"` | `#4A2E3A` |
| UndoLabel | Label | `(280, 600)` | `(200, 50)` | 思源黑体 18pt | `"撤销 x3"` | `#A88F95` |

#### 中部暂停 + 底部道具
| 子节点 | 类型 | 位置 (x, y) | contentSize | 备注 |
|--------|------|-------------|-------------|------|
| PauseBtn | Button | `(330, 600)` | `(80, 80)` | Sprite 主色（蜜桃粉 `#FF6B8B`），按下态深一档 |
| UndoBtn | Button | `(-200, -550)` | `(120, 80)` | 鹅黄 `#FFD166` |
| UndoCountLabel | Label | `(-130, -550)` | `(60, 40)` | 初始 `"x3"`，思源黑体 18pt |
| ShuffleBtn | Button | `(0, -550)` | `(120, 80)` | 鹅黄 `#FFD166` |
| ShuffleCountLabel | Label | `(70, -550)` | `(60, 40)` | 初始 `"x3"` |
| RemoveBtn | Button | `(200, -550)` | `(120, 80)` | 鹅黄 `#FFD166` |
| RemoveCountLabel | Label | `(270, -550)` | `(60, 40)` | 初始 `"x3"` |

**Button 通用设置**（Transition = Sprite）：
- normalSprite：主色/辅助色圆角 sprite
- pressedSprite：同色 -10% 亮度
- disabledSprite：灰紫 `#9B8AA0`
- target：节点自身

#### HUD 整体布局（ASCII）

```
y=+600  [LevelLabel] [ScoreLabel]       [PauseBtn]
y=-550  [UndoBtn x3]  [ShuffleBtn x3]  [RemoveBtn x3]
       ←—— 屏幕宽度 750 ———→
```

---

### 4.8 DialogController + 3 个 Dialog（重点）

#### DialogController 节点
- **类型**：Node + DialogController.ts
- **@property**（共 **16 个**，与 DialogController.ts 一一对应）：
  - `levelCompleteDialog`, `levelFailedDialog`, `pauseDialog` (Node)
  - `completeLevelLabel`, `completeScoreLabel` (Label)
  - `nextBtn`, `shareBtn`, `completeCloseBtn` (Button)
  - `failedLevelLabel`, `failedScoreLabel` (Label)
  - `retryBtn`, `shareRescueBtn`, `failedCloseBtn` (Button)
  - `resumeBtn`, `pauseRetryBtn`, `pauseCloseBtn` (Button)
- **位置**：逻辑节点，位置任意
- **子节点**：3 个 Dialog（每个 active=false）

#### LevelCompleteDialog
- **位置** `(0, 0, 0)`、contentSize `(750, 1334)`、锚点 `(0.5, 0.5)`
- **子节点**：
  - `Mask`：Sprite rgba(0,0,0,0.6) + BlockInputEvents，铺满 750x1334
  - `Card`：Sprite 白底 `#FFFFFF`，contentSize `(600, 700)`，圆角 20px（用 9-slice 或贴图）
  - `TitleLabel`：Label "通关！"，36pt，`#4A2E3A`
  - `CompleteLevelLabel`：Label 初始 `"第 X 关 通关！"`（运行时填），24pt
  - `CompleteScoreLabel`：Label 初始 `"分数 0"`，24pt
  - `NextBtn`：Button "下一关"，主色 `#FF6B8B`，contentSize `(400, 80)`
  - `ShareBtn`：Button "分享"，辅助色 `#FFD166`，contentSize `(400, 80)`
  - `CompleteCloseBtn`：Button "X"，右上角，contentSize `(60, 60)`

#### LevelFailedDialog
同结构，差异：
- `TitleLabel` 初始 `"差一点点"`
- `FailedLevelLabel` 初始 `"第 X 关 失败"`
- `FailedScoreLabel` 初始 `"分数 0"`
- `RetryBtn` 警示色 `#FF5A5A`（重试本关）
- `ShareRescueBtn` 辅助色 `#FFD166`（分享复活）
- `FailedCloseBtn` "X"（只 hide，不回调业务）

#### PauseDialog
同结构，差异：
- `TitleLabel` 初始 `"暂停中"`
- `ResumeBtn` 主色（继续游戏）
- `PauseRetryBtn` 辅助色（重玩本关）
- `PauseCloseBtn` "X"（= 恢复）

**Dialog 通用**：
- 默认 `active = false`（游戏一开始不能显示）
- 入场动画建议：scale `0.8→1.0` + opacity `0→1`，0.25s（art-style.md §6）
- Mask 子节点上加 **BlockInputEvents** 组件防止穿透点击

### 4.9 Main
- **类型**：Node + Main.ts
- **位置**：逻辑节点，位置任意
- **9 个 @property 完整绑定**：

| @property | 类型 | 拖入源 |
|-----------|------|--------|
| `gameManagerNode` | Node | Hierarchy → `GameManager` |
| `audioManagerNode` | Node | Hierarchy → `AudioManager` |
| `board` | Board | Hierarchy → `BoardRoot`（选组件） |
| `levelManager` | LevelManager | Hierarchy → `LevelManager`（选组件） |
| `hud` | HUDController | Hierarchy → `HUD`（选组件） |
| `hintController` | HintController | Hierarchy → `HintController`（选组件） |
| `dialog` | DialogController | Hierarchy → `DialogController`（选组件） |
| `boardHitArea` | Node | Hierarchy → `BoardRoot`（接收点击） |

**怎么拖**：Hierarchy 选中源节点 → 在 Inspector 字段上点 **⊙** 图标 → 选对应节点/组件。

> 注：Main.ts 实际声明了 8 个 @property（不含 hud 是 7 个，加上 hud = 8 个，README 写成 9 个是连同 hintController 在内的总计；以脚本为准共 8 个）。

---

## 5. 初始 string 值速查表

| Label 节点名 | 父节点 | 初始 string | 字体 | 颜色 |
|--------------|--------|-------------|------|------|
| ScoreLabel | HUD | `0` | 思源黑体 24pt | `#4A2E3A` |
| LevelLabel | HUD | `第 1 关` | 思源黑体 24pt | `#4A2E3A` |
| UndoLabel | HUD | `撤销 x3` | 思源黑体 18pt | `#A88F95` |
| UndoCountLabel | HUD | `x3` | 思源黑体 18pt | `#4A2E3A` |
| ShuffleCountLabel | HUD | `x3` | 思源黑体 18pt | `#4A2E3A` |
| RemoveCountLabel | HUD | `x3` | 思源黑体 18pt | `#4A2E3A` |
| TitleLabel | LevelCompleteDialog | `通关！` | 思源黑体 36pt | `#4A2E3A` |
| CompleteLevelLabel | LevelCompleteDialog | `第 X 关 通关！` | 思源黑体 24pt | `#4A2E3A` |
| CompleteScoreLabel | LevelCompleteDialog | `分数 0` | 思源黑体 24pt | `#4A2E3A` |
| TitleLabel | LevelFailedDialog | `差一点点` | 思源黑体 36pt | `#FF5A5A` |
| FailedLevelLabel | LevelFailedDialog | `第 X 关 失败` | 思源黑体 24pt | `#4A2E3A` |
| FailedScoreLabel | LevelFailedDialog | `分数 0` | 思源黑体 24pt | `#4A2E3A` |
| TitleLabel | PauseDialog | `暂停中` | 思源黑体 36pt | `#4A2E3A` |

共 **13 个 Label**，其余 Label（按钮内文字）直接由 Button 子节点 Label 控制。

---

## 6. 验证清单

按场景启动顺序逐项核对：

- [ ] Canvas Design Resolution = 750x1334，Fit Height 开启
- [ ] 背景图显示正确（奶粉色 + 斜纹占位）
- [ ] HUD 顶部 3 个 Label 都显示初始值（Score=`0`，Level=`第 1 关`，Undo=`撤销 x3`）
- [ ] HUD 底部 3 个道具按钮 + PauseBtn 可点击
- [ ] 3 个 Dialog 默认 `active = false`
- [ ] Dialog 内部 Label / Button 已绑定到 DialogController 的 16 个 @property
- [ ] Main.ts 的 8 个 @property 全部拖入（gameManagerNode / audioManagerNode / board / levelManager / hud / hintController / dialog / boardHitArea）
- [ ] `assets/prefabs/Tile.prefab` 存在并被 LevelManager.tilePrefab 引用
- [ ] `assets/resources/levels/level_001.json` 存在
- [ ] ▶ 播放能加载第一关（关卡 1 应有 9 张牌可点）
- [ ] 点击牌能进 slot
- [ ] 凑齐 3 张同 pattern 能消除
- [ ] 通关后 LevelCompleteDialog 弹出
- [ ] 失败时 LevelFailedDialog 弹出且按钮可点
- [ ] 暂停按钮 → PauseDialog 弹出
- [ ] HUD 长按 0.5s → 可点击牌高亮（HintController 验证）

---

## 7. 常见搭建错误

1. **拖错 @property 引用**：同名节点（如两个 Label 都叫 TitleLabel）导致拖错；务必用 Hierarchy 的完整路径定位
2. **Dialog 默认 active 没关**：3 个 Dialog 必须 `active = false`，否则游戏启动就显示弹窗
3. **Canvas Design Resolution 没改**：默认 960x640，UI 全错位；务必设 750x1334
4. **Tile.prefab 默认 SpriteFrame 没设**：运行时一片红；先拖一张占位色块到 Tile.prefab 根 Sprite
5. **关卡 JSON 路径不对**：必须是 `resources/levels/level_xxx.json`（`LevelManager.fetchLevelJson` 用 `resources.load`）
6. **UITransform contentSize 没设**：按钮点不到区域；每个 UI 节点都要设
7. **Label 字体未导入**：显示 `#` 号；提前把 `.ttf` 拖到 `assets/art/font/`
8. **Button Transition 选 Color**：按下无视觉反馈；务必选 Sprite 并配 3 态

---

**完成上面所有步骤后，▶ 播放即可看到关卡 1 的 9 张牌，按 README §"快速开始"流程逐项验证。**