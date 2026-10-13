import { _decorator, Component, EventTouch, Node, Rect, UITransform, Vec2, Vec3, _screen } from 'cc';
import { Tile, TileData, TileSpecial } from './Tile';

const { ccclass, property } = _decorator;

/**
 * 3D 牌堆：维护一个 (x,y,z) 网格，提供"可点击判定"和"点击 hitTest"。
 *
 * 可点击判定规则：
 *   1. 该牌未移除
 *   2. 正上方没有未移除的牌
 *   3. 同层更高 z 的牌不能在屏幕空间上覆盖它（避免 z=2 但偏右下的牌挡住 z=1 的牌）
 */
@ccclass('Board')
export class Board extends Component {
    @property(Node)
    public tileContainer: Node | null = null;

    @property([Node])
    public tilePool: Node[] = [];

    private grid = new Map<string, TileData>();
    private maxZ = 0;

    public get tileCount(): number {
        let n = 0;
        for (const t of this.grid.values()) if (!t.removed) n++;
        return n;
    }

    /** 注册一张牌到网格 */
    addTile(data: Omit<TileData, 'removed' | 'special'> & { special?: TileSpecial }) {
        const full: TileData = { ...data, removed: false, special: data.special ?? 'none' };
        this.grid.set(this.k(full.gx, full.gy, full.gz), full);
        if (full.gz > this.maxZ) this.maxZ = full.gz;
        const tileComp = full.node.getComponent(Tile);
        if (tileComp) tileComp.bind(full);
    }

    isClickable(t: TileData): boolean {
        if (t.removed) return false;
        // 规则 1：正上方有牌就不可点
        for (const other of this.grid.values()) {
            if (other === t || other.removed) continue;
            if (other.gx === t.gx && other.gy === t.gy && other.gz === t.gz + 1) {
                return false;
            }
        }
        // 规则 2：更高 z 的同区域牌覆盖了它的可点击区域
        const myNode = t.node;
        const myUi = myNode.getComponent(UITransform);
        if (!myUi) return true;
        const myBox = myUi.getBoundingBoxToWorld();
        for (const other of this.grid.values()) {
            if (other === t || other.removed || other.gz <= t.gz) continue;
            if (Math.abs(other.gx - t.gx) > 1 || Math.abs(other.gy - t.gy) > 1) continue;
            const otherUi = other.node.getComponent(UITransform);
            if (!otherUi) continue;
            if (otherUi.getBoundingBoxToWorld().intersects(myBox)) return false;
        }
        return true;
    }

    /** 全局点击事件 → 命中牌 → 回调 */
    hitTest(worldPos: Vec3): TileData | null {
        // 从最高 z 向下找，先命中先返回
        for (let z = this.maxZ; z >= 0; z--) {
            for (const t of this.grid.values()) {
                if (t.removed || t.gz !== z) continue;
                const ui = t.node.getComponent(UITransform);
                if (!ui) continue;
                if (ui.getBoundingBoxToWorld().contains(new Vec2(worldPos.x, worldPos.y))) {
                    return t;
                }
            }
        }
        return null;
    }

    /** 从池里取一张节点（如果没有就克隆第一张）。返回的 Node 已 setParent 到 tileContainer */
    acquireTileNode(): Node {
        let node: Node | null = this.tilePool.pop() ?? null;
        if (!node && this.tilePool.length === 0 && this.tileContainer) {
            // 池空：克隆第一张预制体（在编辑器里把第一张 Tile.prefab 拖到这里）
            // 注意：实际项目应在加载关卡前预实例化一个池
            console.warn('[Board] tile pool is empty, please prefill in editor');
        }
        if (!node) {
            node = new Node('Tile');
        }
        if (this.tileContainer && node.parent !== this.tileContainer) {
            node.setParent(this.tileContainer);
        }
        return node;
    }

    /** 牌消除动画结束后回收节点 */
    releaseTileNode(node: Node) {
        node.removeFromParent();
        this.tilePool.push(node);
    }

    /** 通关判定 */
    isCleared(): boolean {
        return this.tileCount === 0;
    }

    /** 找出场上所有指定 pattern 且未消除的 normal 牌。bomb 触发连锁消除时用 */
    findAllByPattern(pattern: number): TileData[] {
        const out: TileData[] = [];
        for (const t of this.grid.values()) {
            if (!t.removed && t.special === 'none' && t.pattern === pattern) out.push(t);
        }
        return out;
    }

    /** 遍历所有未消除的牌（含 special）。Hint 控制器、Shuffle 等需要枚举时用 */
    forEachActive(cb: (t: TileData) => void) {
        for (const t of this.grid.values()) {
            if (!t.removed) cb(t);
        }
    }

    /** 物理坐标 → 网格坐标。origin 锚点在容器中心，cellSize 是格子宽高 */
    worldToGrid(worldPos: Vec3, origin: Vec3, cellW: number, cellH: number): { gx: number; gy: number } {
        const local = worldPos.subtract(origin);
        const gx = Math.round(local.x / cellW);
        const gy = Math.round(-local.y / cellH);   // y 轴取负让上层为正
        return { gx, gy };
    }

    /** 网格坐标 → 节点世界坐标。用来初始化时摆牌 */
    gridToWorld(gx: number, gy: number, gz: number, origin: Vec3, cellW: number, cellH: number, layerOffset: number): Vec3 {
        const x = origin.x + gx * cellW;
        const y = origin.y - gy * cellH + gz * layerOffset;
        return new Vec3(x, y, 0);
    }

    private k(x: number, y: number, z: number) {
        return `${x},${y},${z}`;
    }
}
