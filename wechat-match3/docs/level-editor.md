# 关卡编辑器工作流设计

> 目标：批量产出 L6~L50 共 45 关，兼顾难度曲线与可玩性。
> 适配版本：当前项目（`wechat-match3/`，Cocos Creator 3.x + TypeScript）。

---

## 1. 需求分析

**目标**：在已有 L1~L5 手写 JSON 的基础上，批量产出 L6~L50（45 关）。

**三种关卡类型**：

| 类型 | 范围 | 数量 | 制作方式 |
|------|------|------|----------|
| 常规关 | L6~L40 | 35 | 程序生成 + 难度曲线 |
| BOSS 关 | L41~L45 | 5 | 手工雕琢 |
| 彩蛋关 | L46~L50 | 5 | 手工雕琢（特殊主题） |

**难度维度**（每关由以下 5 个参数共同决定）：

- **总牌数** `totalTiles`：覆盖范围 24~120
- **pattern 种类数** `patternCount`：3~8
- **层数** `layerCount`（gz 范围）：1~6
- **特殊牌数量** `bomb + wild`：0~12
- **空间密度** `density`：0~1，控制堆叠紧密度

从 L1~L5 观察到的曲线：每关 +6~24 张牌，每关 +0~1 层，L4 起引入 wild，L5 起引入 bomb。

---

## 2. 方案对比

### 方案 A：Cocos 编辑器内嵌关卡编辑器

在 Cocos 里做一个 EditorScene，把所有牌摆到场景中可视化编辑，导出 JSON。

- **优点**：所见即所得；与游戏共用坐标系与校验代码
- **缺点**：写 Editor 扩展成本高（panel + 自定义 gizmo）；不能批量生成；依赖编辑器打开、不可 CI 化
- **适用**：手工精细调整少量关键关（如 L41~L50）

### 方案 B：独立 Web 工具（HTML + Canvas + TypeScript）

浏览器里的独立可视化编辑器，独立的 React/Vue 项目，部署到团队内网。

- **优点**：纯前端好部署；支持批量预览；可视化调试方便
- **缺点**：与项目割裂（坐标系、特殊牌枚举都要复刻）；需要打包发布；需要长期维护一个前端项目
- **适用**：批量产出 + 后期可视化微调

### 方案 C：声明式 + 程序化生成

写一个关卡生成脚本（TypeScript），用规则生成 JSON。

- **优点**：批量快；参数化难度曲线；可重现（seed）；可单测
- **缺点**：生成结果有随机性；需要后置手工筛选
- **适用**：快速产出大量候选关

### 方案 D：表格驱动（CSV → JSON 转换脚本）

关卡参数在 CSV 里（一行一关），Python/Node 脚本读 CSV 生成 JSON。

- **优点**：策划友好（非程序员可调）；批量最快；版本控制友好（diff 清晰）
- **缺点**：空间布局表达受限；只能参数化（适合"模板化"空间而非手摆）
- **适用**：参数化关卡 + 固定空间模板

---

## 3. 推荐方案：C + D 组合

**我推荐 C + D**——程序化生成配合 CSV 参数驱动：

1. **CSV 参数表** 维护 L6~L40 的难度曲线（每行一关）
2. **TypeScript 生成器** 读 CSV + 空间模板 → 输出 `level_xxx.json`
3. **手工雕琢** L41~L50 BOSS / 彩蛋关（直接编辑 JSON，或用方案 A 可视化摆牌）

理由：C 负责"批量生成"，D 负责"策划友好调参"，两者互补。L5 的手工细节（特定位置塞 wild/bomb）证明纯生成不够，但纯手写 45 关又不现实。

---

## 4. CSV 参数表样例

CSV 文件位置：`tools/level-params.csv`

| levelId | totalTiles | patternCount | layerCount | bombCount | wildCount | difficulty | slotCapacity | density |
|---------|------------|--------------|------------|-----------|-----------|------------|--------------|---------|
| 6 | 24 | 4 | 2 | 0 | 0 | easy | 7 | 0.5 |
| 7 | 30 | 5 | 2 | 0 | 0 | easy | 7 | 0.5 |
| 8 | 36 | 5 | 3 | 0 | 0 | easy | 7 | 0.6 |
| 12 | 48 | 6 | 3 | 0 | 2 | normal | 7 | 0.6 |
| 20 | 72 | 7 | 4 | 2 | 2 | normal | 7 | 0.7 |
| 30 | 90 | 8 | 5 | 3 | 3 | hard | 7 | 0.8 |
| 40 | 108 | 8 | 5 | 4 | 4 | hard | 7 | 0.8 |
| 41 | 90 | 7 | 5 | 6 | 6 | boss | 7 | 0.9 |
| 46 | 60 | 1 | 2 | 30 | 0 | easter | 7 | 0.6 |

**参数说明**：

| 列 | 类型 | 说明 |
|----|------|------|
| levelId | int | 关卡 ID，需与文件名 `level_xxx.json` 一致 |
| totalTiles | int | 总牌数（含 bomb + wild） |
| patternCount | int | 主图案种类数（3-8） |
| layerCount | int | z 层级数（1-6） |
| bombCount | int | 炸弹（special=bomb）数量 |
| wildCount | int | 万能（special=wild）数量 |
| difficulty | enum | easy / normal / hard / boss / easter |
| slotCapacity | int | 槽位容量（默认 7，调试可用 5） |
| density | float | 空间密度 0-1，影响堆叠紧密度 |

---

## 5. 生成器接口设计

伪代码（`tools/level-generator.ts`）：

```typescript
import { LevelJson, TileSpec } from '../assets/scripts/game/LevelManager';

interface LevelGenParams {
    levelId: number;
    totalTiles: number;
    patternCount: number;
    layerCount: number;
    bombCount: number;
    wildCount: number;
    density: number;
    slotCapacity: number;
    seed?: number;            // 可选：固定 seed 复现
}

function generateLevel(p: LevelGenParams): LevelJson {
    const normalCount = p.totalTiles - p.bombCount - p.wildCount;
    if (normalCount <= 0) throw new Error('normalCount must be > 0');
    if (normalCount % 3 !== 0) {
        throw new Error(`normalCount=${normalCount} 非 3 倍数，调整 totalTiles`);
    }

    // 1. 分配 pattern：确保每个 pattern 的 normal 牌数是 3 的倍数
    const perPattern = normalCount / p.patternCount;
    if (perPattern % 3 !== 0) {
        // 调整 patternCount 直到 normalCount / patternCount 是 3 的倍数
        // 或就近吸附 normalCount
    }

    // 2. 生成网格坐标（gx ∈ [0,2]、gy ∈ [0,...]、gz ∈ [0,layerCount)）
    const positions = generatePositions(p.totalTiles, p.layerCount, p.density, p.seed);

    // 3. 把 pattern + special 随机分配到位置
    const tiles = distributeToPositions(
        positions,
        p.patternCount,
        p.bombCount,
        p.wildCount,
        p.seed
    );

    // 4. 校验 + 装入 LevelJson
    return validateAndPackage(tiles, p);
}

// 空间模板：gx ∈ [0,2]，gy 由 (totalTiles / layerCount) 决定
function generatePositions(n: number, layers: number, density: number, seed?: number) {
    // 计算每层目标牌数
    const perLayer = Math.ceil(n / layers);
    // 横向 3 格、纵向 ceil(perLayer/3)、z 0..layers-1
    // 按 density 决定是否每格都填（1.0=满）或随机抽稀
    // 输出 {gx, gy, gz}[]
}

// 分配逻辑：先随机挑 special 位置，剩余按 patternCount 分桶
function distributeToPositions(positions, patternCount, bombCount, wildCount, seed?) {
    // 1. 从 positions 随机挑 bombCount + wildCount 个位置
    // 2. 剩余位置按 patternCount 平分（每桶 3 的倍数）
    // 3. 输出 TileSpec[]
}

function validateAndPackage(tiles: TileSpec[], p: LevelGenParams): LevelJson {
    // 调 LevelManager.validateLevel 风格的校验
    // 计算 origin：让 (0,0,0) 居中向左下偏移
    return {
        levelId: p.levelId,
        slotCapacity: p.slotCapacity,
        cellWidth: 80,
        cellHeight: 80,
        layerOffset: 30,
        origin: { x: -80, y: 200 },  // 按总牌数动态算
        tiles,
    };
}
```

---

## 6. 空间模板

观察 L1~L5：grid 横向固定 3 格（gx 0-2），纵向与层数随牌数扩。给出 3 种典型模板：

```
模板 1：easy（稀疏 1-2 层）
gx: 0 1 2
gz=0
gy: 2 | X X X
    1 | X X X
    0 | X X X
gz=1（可选）
gy: 2 | X X X
    1 | X X X
    0 | X X X
合计 9~18 张
```

```
模板 2：normal（中等堆叠 3-4 层）
gz=0,1,2 三层交错
   |  gz=2
   |  gz=1
   |  gz=0
   v
合计 27~48 张
每层内填 3×N 矩形，density≈0.6（有空格但不连续大片空）
```

```
模板 3：boss（多层堆叠 5-6 层）
gz=0 顶层：3×2=6 张
gz=1     ：3×3=9 张
gz=2     ：3×4=12 张
gz=3     ：3×4=12 张
gz=4     ：3×3=9 张
gz=5（彩蛋层）
合计 48~72 张，density≈0.9，几乎每格满
+ bomb/wild 散布在 gz=0 和 gz=4~5 边界
```

---

## 7. 工作流（流程图）

```
+------------------+     +-------------------+     +-------------------+     +------------------+
| 策划             | --> | level-params.csv  | --> | level-generator.ts| --> | level_xxx.json   |
| 在 Excel 调参数  |     | (tools/)          |     | (tools/)          |     | (resources/levels)|
+------------------+     +-------------------+     +-------------------+     +------------------+
                                                                                       |
                                                                                       v
                                                                          +-------------------------+
                                                                          | LevelManager.validate   |
                                                                          | (游戏内 warn-only 校验) |
                                                                          +-------------------------+
                                                                                       |
                                                                        +--------------+--------------+
                                                                        |                             |
                                                                        v                             v
                                                                +---------------+         +-----------------------+
                                                                | 通过：直接提测 |         | 失败：人工修改 CSV/JSON|
                                                                +---------------+         +-----------------------+
                                                                                                    |
                                                                                                    v
                                                                                            +---------------+
                                                                                            | L41~L50       |
                                                                                            | 手工雕琢      |
                                                                                            | (Cocos/直接JSON)|
                                                                                            +---------------+
```

CLI 调用示例：
```bash
# 批量生成 L6~L40（读 CSV）
npx ts-node tools/level-generator.ts --csv tools/level-params.csv --range 6-40

# 单关生成（手工测试）
npx ts-node tools/level-generator.ts --levelId 6 --seed 42
```

---

## 8. 实现优先级

- **高（先做）**：`tools/level-generator.ts` 主程序（固定参数跑通 L6~L20）
  - 先打平 L6~L20 的 15 关，验证可玩性
  - 实现 `generatePositions` + `distributeToPositions` 核心函数
- **中**：CSV 参数表 + 转换脚本 + 难度曲线规划
  - 用 Excel 维护 L6~L50 参数（先 L6~L20）
  - 跑通 `--csv` 全流程
  - 接 `--seed` 复现
- **低（最后做）**：Cocos 编辑器内嵌编辑器，仅 L41~L45 BOSS、L46~L50 彩蛋关用
  - 这 10 关手工雕琢 1-2 周可完成，不阻塞主线

---

## 9. 验证手段

1. **可玩性抽测**：先批量生成 5 关（程序 seed=42~46），手动跑游戏确认：
   - 无死局（无可点牌 + slot 未满）
   - 至少有 1 种通关路径
2. **难度曲线平滑性**：让 3 名测试人员打 L1~L10，统计通关率
   - 期望通关率单调下降：L1=100% → L10≈60%
3. **最少点击次数**：每关输出"理论最少点击次数 = 总牌数 / slotCapacity"
   - 期望范围 5~20 次
   - 超出范围说明参数失衡，需调整 `totalTiles` 或 `slotCapacity`
4. **CI 校验**：把 `LevelManager.validateLevel` 风格的不变量（normal 牌 3 倍数、tiles 总数 3 倍数）写进 `tools/level-generator.ts` 的 `validateAndPackage`，生成即校验

---

## 附：文件名与坐标约定

- 文件名：`assets/resources/levels/level_xxx.json`（`xxx` 三位补零）
- 网格：gx ∈ [0,2]、gy ∈ [0,...]、gz ∈ [0,...]
- origin：根据 `totalTiles` 与 `layerCount` 动态居中，参考 L5 的 `x: -240, y: 280`

字数：约 1700 字（含表格与代码块）。
