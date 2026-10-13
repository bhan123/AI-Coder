/**
 * 关卡生成器 (L6~L50 批量生产工具)
 *
 * 设计目标：
 *   - 从 LevelGenParams（CSV 或硬编码）生成符合 LevelJson schema 的关卡 JSON
 *   - 校验 normal 牌总数 % 3 == 0、每 pattern 牌数 % 3 == 0
 *   - 支持 --csv / --range / --seed / --write CLI
 *
 * 使用：
 *   npx tsx tools/level-generator.ts --range 6-20 --write
 *   npx tsx tools/level-generator.ts --csv tools/level-params.csv --write
 *   npx tsx tools/level-generator.ts --levelId 6 --seed 42     # print 到 stdout
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';

// ESM 兼容：__dirname 在 ESM 模式下未定义
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// ===================== 1. 类型定义 =====================

export interface LevelGenParams {
    levelId: number;
    totalTiles: number;
    patternCount: number;
    layerCount: number;
    bombCount: number;
    wildCount: number;
    density: number;       // 0..1，堆叠密度
    slotCapacity: number;
}

interface Position {
    gx: number;
    gy: number;
    gz: number;
}

interface TileSpec extends Position {
    pattern: number;
    special: 'none' | 'bomb' | 'wild';
}

interface LevelJson {
    levelId: number;
    slotCapacity: number;
    cellWidth: number;
    cellHeight: number;
    layerOffset: number;
    origin: { x: number; y: number };
    tiles: Array<{
        pattern: number;
        gx: number;
        gy: number;
        gz: number;
        special?: 'none' | 'bomb' | 'wild';
    }>;
}

interface ValidationResult {
    ok: boolean;
    warnings: string[];
}

// ===================== 2. 工具函数 =====================

/**
 * mulberry32 — 32 位种子 PRNG，速度快、可复现
 */
function mulberry32(seed: number): () => number {
    let a = seed >>> 0;
    return function () {
        a = (a + 0x6D2B79F5) >>> 0;
        let t = a;
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
}

/** Fisher-Yates 原地洗牌 */
function shuffle<T>(arr: T[], rng: () => number): void {
    for (let i = arr.length - 1; i > 0; i--) {
        const j = Math.floor(rng() * (i + 1));
        [arr[i], arr[j]] = [arr[j], arr[i]];
    }
}

/** 简单 CSV 解析：按 header 名映射到 LevelGenParams 字段 */
function parseCsv(text: string): LevelGenParams[] {
    const lines = text.trim().split(/\r?\n/);
    if (lines.length < 2) return [];
    const header = lines[0].split(',').map(s => s.trim());
    const out: LevelGenParams[] = [];
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line || line.startsWith('#')) continue;
        const cells = line.split(',').map(s => s.trim());
        const obj: Record<string, unknown> = {};
        header.forEach((h, idx) => {
            const cell = cells[idx] ?? '';
            const n = Number(cell);
            obj[h] = cell === '' || Number.isNaN(n) ? cell : n;
        });
        // 兼容 'difficulty' 列存在但不影响生成
        out.push(obj as unknown as LevelGenParams);
    }
    return out;
}

// ===================== 3. 核心生成 =====================

/**
 * 根据 layerCount 决定每层网格大小（gx ∈ [0,2]，gy 递增，gz ∈ [0,layerCount)）
 * 用 density 过滤位置，再 Fisher-Yates 洗后取前 totalTiles 个
 *
 * 策略：
 *   1. 先按 layerCount 算出"经验行数表"，再生成所有候选位置
 *   2. 如果候选数 < totalTiles，向上扩展行数直到足够
 *   3. 按 density 过滤（保留概率 = density + 0.2），保证候选数 >= totalTiles
 *   4. Fisher-Yates 洗后取前 totalTiles 个
 */
function generatePositions(p: LevelGenParams, rng: () => number): Position[] {
    const { layerCount, density } = p;
    // 经验行数表（每层 gy 行数）
    const rowsPerLayer: Record<number, number[]> = {
        1: [6],
        2: [5, 4],
        3: [5, 5, 4],
        4: [5, 5, 4, 4],
        5: [6, 5, 5, 4, 4],
    };

    // 自适应扩展：若初始行数不够，按 totalTiles 向上扩展
    const baseRows = rowsPerLayer[layerCount] ?? Array(layerCount).fill(4);
    const baseTotal = baseRows.reduce((a, b) => a + b, 0) * 3; // 每行 3 列
    let rows: number[];
    if (baseTotal < p.totalTiles) {
        const need = Math.ceil((p.totalTiles - baseTotal) / 3);
        // 把多余的 need 行优先加到底层
        rows = baseRows.slice();
        let i = 0;
        let added = 0;
        while (added < need) {
            rows[i % layerCount] += 1;
            i += 1;
            added += 1;
        }
    } else {
        rows = baseRows;
    }

    // 生成候选位置网格
    let candidates: Position[] = [];
    for (let gz = 0; gz < layerCount; gz++) {
        const rowsThis = rows[gz] ?? 4;
        for (let gy = 0; gy < rowsThis; gy++) {
            for (let gx = 0; gx < 3; gx++) {
                candidates.push({ gx, gy, gz });
            }
        }
    }

    // 按 density 过滤：保留概率 = density + 0.2（保底），但要保证过滤后 >= totalTiles
    const keepProb = Math.min(1, density + 0.2);
    let filtered: Position[] = [];
    for (const pos of candidates) {
        if (rng() < keepProb) filtered.push(pos);
    }
    // 兜底 1：若不够，把被过滤的补回来（按 rng 顺序）
    if (filtered.length < p.totalTiles) {
        const set = new Set(filtered.map(p => `${p.gx},${p.gy},${p.gz}`));
        const rest = candidates.filter(c => !set.has(`${c.gx},${c.gy},${c.gz}`));
        shuffle(rest, rng);
        for (const r of rest) {
            if (filtered.length >= p.totalTiles) break;
            filtered.push(r);
        }
    }

    shuffle(filtered, rng);
    return filtered.slice(0, p.totalTiles);
}

/**
 * 生成 pattern 桶：每 pattern 出现 perPattern 次（normalCount/patternCount），
 * 严格保证 normalCount % 3 == 0 && (normalCount / patternCount) % 3 == 0
 *
 * 步骤：
 *   1. 先 fill 每 pattern = base 次（base 必为 3 倍数）
 *   2. 剩余散到前 remainder 个 pattern（每个 +3）
 *   3. bombCount + wildCount 个位置随机挑出
 *   4. Fisher-Yates 洗 tile spec 顺序
 */
function distributeToTiles(
    positions: Position[],
    p: LevelGenParams,
    rng: () => number
): TileSpec[] {
    const normalCount = p.totalTiles - p.bombCount - p.wildCount;
    if (normalCount <= 0) {
        throw new Error(`normalCount must be > 0 (got ${normalCount})`);
    }
    if (normalCount % 3 !== 0) {
        throw new Error(
            `normalCount=${normalCount} 不是 3 的倍数，调整 totalTiles / bombCount / wildCount`
        );
    }
    if (positions.length !== p.totalTiles) {
        throw new Error(
            `positions.length (${positions.length}) != totalTiles (${p.totalTiles})`
        );
    }
    // 强制约束：每 pattern 数量必须为 3 的倍数
    // 把 normalCount 拆成 patternCount 个 3 的倍数之和
    // 先均分 base = round(normalCount/patternCount)，再调整使每桶 % 3 == 0
    const perPattern = normalCount / p.patternCount;
    if (perPattern < 3) {
        throw new Error(
            `L${p.levelId}: 每 pattern 仅 ${perPattern} 张 (<3)，请增加 totalTiles 或减少 patternCount`
        );
    }
    // 构造 pattern 桶：每桶 = floor(perPattern/3)*3，向下取整
    const baseMultiple = Math.floor(perPattern / 3) * 3;
    const buckets: number[] = new Array(p.patternCount).fill(baseMultiple);
    let used = baseMultiple * p.patternCount;
    // 余数 normalCount - used，按 3 一组均匀散到 buckets（轮转）
    let leftover = normalCount - used;
    let bIdx = Math.floor(rng() * p.patternCount); // 起点随机化
    while (leftover >= 3) {
        buckets[bIdx % p.patternCount] += 3;
        leftover -= 3;
        bIdx += 1;
    }
    if (leftover !== 0) {
        // 理论上 leftover 必为 0（因为 baseMultiple 是 3 倍数、normalCount 是 3 倍数）
        throw new Error(
            `L${p.levelId}: leftover=${leftover}，pattern 桶分配失败`
        );
    }

    // 展平成一维 pattern 列表
    const patternList: number[] = [];
    for (let pat = 0; pat < p.patternCount; pat++) {
        for (let k = 0; k < buckets[pat]; k++) {
            patternList.push(pat);
        }
    }
    shuffle(patternList, rng);

    // 2. 从 positions 里随机挑 bombCount + wildCount 个位置
    const shuffledPositions = [...positions];
    shuffle(shuffledPositions, rng);
    const specialCount = p.bombCount + p.wildCount;
    const specialPositions = shuffledPositions.slice(0, specialCount);
    const normalPositions = shuffledPositions.slice(specialCount);

    // 3. 决定每个 special 位置是 bomb 还是 wild（按 bombCount 优先）
    const specialTiles: TileSpec[] = [];
    const bombIndices = new Set<number>();
    for (let i = 0; i < p.bombCount; i++) bombIndices.add(i);
    for (let i = 0; i < specialPositions.length; i++) {
        const pos = specialPositions[i];
        const special: 'bomb' | 'wild' = bombIndices.has(i) ? 'bomb' : 'wild';
        // special 牌需要一个占位 pattern（视觉占位），从已有 pattern 中随机选
        const pat = Math.floor(rng() * p.patternCount);
        specialTiles.push({
            gx: pos.gx,
            gy: pos.gy,
            gz: pos.gz,
            pattern: pat,
            special,
        });
    }

    // 4. normal 牌按 patternList 顺序填到 normalPositions
    const normalTiles: TileSpec[] = [];
    for (let i = 0; i < normalPositions.length; i++) {
        const pos = normalPositions[i];
        normalTiles.push({
            gx: pos.gx,
            gy: pos.gy,
            gz: pos.gz,
            pattern: patternList[i],
            special: 'none',
        });
    }

    // 5. 合并洗牌
    const allTiles = [...normalTiles, ...specialTiles];
    shuffle(allTiles, rng);
    return allTiles;
}

/**
 * 复用 LevelManager.validateLevel 风格的校验
 */
function validateLevelSpec(level: LevelJson): ValidationResult {
    const warnings: string[] = [];
    // tiles.length % 3
    if (level.tiles.length % 3 !== 0) {
        warnings.push(`tiles.length=${level.tiles.length} 不是 3 的倍数`);
    }
    // 每个 pattern 的 normal 牌数 % 3
    const counts = new Map<number, number>();
    let bomb = 0;
    let wild = 0;
    for (const t of level.tiles) {
        if (t.special === 'bomb') bomb += 1;
        else if (t.special === 'wild') wild += 1;
        else counts.set(t.pattern, (counts.get(t.pattern) ?? 0) + 1);
    }
    for (const [pat, c] of counts) {
        if (c % 3 !== 0) {
            warnings.push(`pattern ${pat} 有 ${c} 张 normal 牌，不是 3 的倍数`);
        }
    }
    // gz 范围
    let maxGz = 0;
    for (const t of level.tiles) {
        if (t.gz > maxGz) maxGz = t.gz;
    }
    if (maxGz >= 8) {
        warnings.push(`gz 最大值 ${maxGz} 超出合理范围 (<8)`);
    }
    return { ok: warnings.length === 0, warnings };
}

/**
 * 根据 totalTiles 与 layerCount 计算 origin，让牌堆视觉居中
 * 参考 L1~L5 的 origin 取值：
 *   L1 (9 tiles):   x=-120, y=120
 *   L2 (18 tiles):  x=-160, y=120
 *   L3 (30 tiles):  x=-200, y=160
 *   L4 (36 tiles):  x=-200, y=160
 *   L5 (66 tiles):  x=-240, y=280
 */
function computeOrigin(totalTiles: number, layerCount: number): { x: number; y: number } {
    // 经验公式：x = -(3 * cellWidth / 2) - 偏移，y 根据层数提升
    const baseX = -120;
    const xStep = Math.max(0, Math.floor((totalTiles - 9) / 12)) * 20;
    const x = baseX - xStep;
    const y = 120 + Math.max(0, layerCount - 1) * 40;
    return { x, y };
}

/**
 * 主生成入口
 */
function generateLevel(p: LevelGenParams, seed?: number): LevelJson {
    const rng = mulberry32((seed ?? p.levelId * 1000 + 42) >>> 0);
    const positions = generatePositions(p, rng);
    const tiles = distributeToTiles(positions, p, rng);
    const origin = computeOrigin(p.totalTiles, p.layerCount);
    const level: LevelJson = {
        levelId: p.levelId,
        slotCapacity: p.slotCapacity,
        cellWidth: 80,
        cellHeight: 80,
        layerOffset: 30,
        origin,
        tiles,
    };
    // 校验
    const result = validateLevelSpec(level);
    if (!result.ok) {
        for (const w of result.warnings) console.warn(`[L${p.levelId}] ${w}`);
    }
    return level;
}

// ===================== 4. 批量 =====================

function generateBatch(paramsList: LevelGenParams[], seed?: number): LevelJson[] {
    return paramsList.map(p => generateLevel(p, seed));
}

function loadParamsFromCsv(csvPath: string): LevelGenParams[] {
    const abs = path.resolve(csvPath);
    const text = fs.readFileSync(abs, 'utf-8');
    return parseCsv(text);
}

// ===================== 5. L6~L20 参数表（验证用，未来用 CSV 替代） =====================

export const L6_TO_L20_PARAMS: LevelGenParams[] = [
    { levelId: 6,  totalTiles: 24, patternCount: 4, layerCount: 2, bombCount: 0, wildCount: 0, density: 0.55, slotCapacity: 7 },
    { levelId: 7,  totalTiles: 30, patternCount: 5, layerCount: 2, bombCount: 0, wildCount: 0, density: 0.60, slotCapacity: 7 },
    { levelId: 8,  totalTiles: 27, patternCount: 3, layerCount: 2, bombCount: 0, wildCount: 3, density: 0.60, slotCapacity: 7 },
    { levelId: 9,  totalTiles: 36, patternCount: 4, layerCount: 3, bombCount: 0, wildCount: 0, density: 0.65, slotCapacity: 7 },
    { levelId: 10, totalTiles: 39, patternCount: 3, layerCount: 3, bombCount: 0, wildCount: 0, density: 0.65, slotCapacity: 7 },
    { levelId: 11, totalTiles: 45, patternCount: 5, layerCount: 3, bombCount: 3, wildCount: 0, density: 0.70, slotCapacity: 7 },
    { levelId: 12, totalTiles: 48, patternCount: 4, layerCount: 3, bombCount: 3, wildCount: 0, density: 0.70, slotCapacity: 7 },
    { levelId: 13, totalTiles: 54, patternCount: 6, layerCount: 3, bombCount: 0, wildCount: 3, density: 0.75, slotCapacity: 7 },
    { levelId: 14, totalTiles: 60, patternCount: 5, layerCount: 4, bombCount: 3, wildCount: 3, density: 0.75, slotCapacity: 7 },
    { levelId: 15, totalTiles: 57, patternCount: 3, layerCount: 4, bombCount: 3, wildCount: 3, density: 0.80, slotCapacity: 7 },
    { levelId: 16, totalTiles: 66, patternCount: 6, layerCount: 4, bombCount: 3, wildCount: 3, density: 0.80, slotCapacity: 7 },
    { levelId: 17, totalTiles: 72, patternCount: 6, layerCount: 4, bombCount: 6, wildCount: 0, density: 0.80, slotCapacity: 7 },
    { levelId: 18, totalTiles: 75, patternCount: 5, layerCount: 4, bombCount: 6, wildCount: 3, density: 0.85, slotCapacity: 7 },
    { levelId: 19, totalTiles: 81, patternCount: 3, layerCount: 5, bombCount: 9, wildCount: 3, density: 0.85, slotCapacity: 7 },
    { levelId: 20, totalTiles: 90, patternCount: 6, layerCount: 5, bombCount: 9, wildCount: 3, density: 0.90, slotCapacity: 7 },
];

// 自检：每关 normalCount 是否 3 的倍数
function sanityCheckParams(params: LevelGenParams[]): string[] {
    const errs: string[] = [];
    for (const p of params) {
        const normal = p.totalTiles - p.bombCount - p.wildCount;
        if (normal <= 0) {
            errs.push(`L${p.levelId}: normal=${normal} <= 0`);
        } else if (normal % 3 !== 0) {
            errs.push(`L${p.levelId}: normal=${normal} 不是 3 倍数`);
        }
        if (normal / p.patternCount < 3) {
            errs.push(`L${p.levelId}: 每 pattern 仅 ${normal / p.patternCount} 张 (<3)`);
        }
    }
    return errs;
}

// ===================== 6. CLI 入口 =====================

interface CliArgs {
    csv?: string;
    seed?: number;
    write: boolean;
    range?: [number, number];
    levelId?: number;
    outDir?: string;
}

function parseArgs(argv: string[]): CliArgs {
    const out: CliArgs = { write: false };
    for (let i = 0; i < argv.length; i++) {
        const a = argv[i];
        if (a === '--csv') {
            out.csv = argv[++i];
        } else if (a === '--seed') {
            out.seed = Number(argv[++i]);
        } else if (a === '--write') {
            out.write = true;
        } else if (a === '--range') {
            const [s, e] = (argv[++i] ?? '').split('-').map(Number);
            if (!Number.isNaN(s) && !Number.isNaN(e)) out.range = [s, e];
        } else if (a === '--levelId') {
            out.levelId = Number(argv[++i]);
        } else if (a === '--outDir') {
            out.outDir = argv[++i];
        }
    }
    return out;
}

async function main() {
    const args = parseArgs(process.argv.slice(2));

    // 默认 outDir
    const projectRoot = path.resolve(__dirname, '..');
    const defaultOutDir = path.join(projectRoot, 'assets', 'resources', 'levels');
    const outDir = args.outDir ?? defaultOutDir;

    // 决定参数列表
    let paramsList: LevelGenParams[] = [];
    if (args.csv) {
        paramsList = loadParamsFromCsv(args.csv);
        console.log(`[level-gen] 读 CSV ${args.csv}，${paramsList.length} 关`);
    } else {
        paramsList = [...L6_TO_L20_PARAMS];
    }

    // 范围过滤
    if (args.range) {
        const [s, e] = args.range;
        paramsList = paramsList.filter(p => p.levelId >= s && p.levelId <= e);
    }
    if (typeof args.levelId === 'number') {
        paramsList = paramsList.filter(p => p.levelId === args.levelId);
    }

    if (paramsList.length === 0) {
        console.error('[level-gen] 参数列表为空，检查 --csv / --range / --levelId');
        process.exit(1);
    }

    // 自检参数
    const sanityErrs = sanityCheckParams(paramsList);
    if (sanityErrs.length > 0) {
        console.error('[level-gen] 参数自检失败：');
        for (const e of sanityErrs) console.error('  - ' + e);
        process.exit(1);
    }

    // 生成
    const levels = generateBatch(paramsList, args.seed);

    // 输出
    if (args.write) {
        fs.mkdirSync(outDir, { recursive: true });
        for (const lv of levels) {
            const fname = `level_${String(lv.levelId).padStart(3, '0')}.json`;
            const fpath = path.join(outDir, fname);
            fs.writeFileSync(fpath, JSON.stringify(lv, null, 2), 'utf-8');
        }
        console.log(`[level-gen] 写入 ${levels.length} 关到 ${outDir}`);
    } else {
        // 默认 print 第一个到 stdout
        const first = levels[0];
        process.stdout.write(JSON.stringify(first, null, 2) + '\n');
    }

    // 报告统计
    console.error('');
    console.error('===== 生成统计 =====');
    console.error(
        'Lvl | total | pat | bomb | wild | normal | layers | tiles_written | warnings'
    );
    console.error(
        '----|-------|-----|------|------|--------|--------|---------------|---------'
    );
    for (const lv of levels) {
        const p = paramsList.find(x => x.levelId === lv.levelId)!;
        const bomb = lv.tiles.filter(t => t.special === 'bomb').length;
        const wild = lv.tiles.filter(t => t.special === 'wild').length;
        const norm = lv.tiles.filter(t => !t.special || t.special === 'none').length;
        const r = validateLevelSpec(lv);
        console.error(
            `${String(lv.levelId).padStart(3)} | ${String(p.totalTiles).padStart(5)} | ${String(
                p.patternCount
            ).padStart(3)} | ${String(bomb).padStart(4)} | ${String(wild).padStart(4)} | ${String(
                norm
            ).padStart(6)} | ${String(p.layerCount).padStart(6)} | ${String(
                lv.tiles.length
            ).padStart(13)} | ${r.warnings.length === 0 ? 'OK' : r.warnings.join('; ')}`
        );
    }
}

main().catch(err => {
    console.error(err);
    process.exit(1);
});
