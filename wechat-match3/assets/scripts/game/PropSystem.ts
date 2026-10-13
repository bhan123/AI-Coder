import { Tween, Vec3 } from 'cc';
import { GameManager, PropType } from '../core/GameManager';
import { Board } from './Board';
import { Tile, TileData } from './Tile';
import { MatchSystem } from './MatchSystem';

export interface PropSystemGeometry {
    origin: Vec3;
    cellWidth: number;
    cellHeight: number;
    layerOffset: number;
}

/**
 * 道具系统：
 * - undo: 走 MatchSystem.undoLast()
 * - shuffle: 把场上所有未消除的 normal 牌重新分配网格坐标（保持 pattern/special），
 *            然后 Tween 到新位置；special 牌保持当前坐标
 * - remove: 扫描场上是否存在某 pattern 计数 ≥ 3；若有，直接消除前 3 张；否则什么都不做
 *
 * 所有道具入口 useProp(type)：先扣 GameManager.propCounts[type]；成功后执行对应效果。
 */
export class PropSystem {
    private board: Board;
    private matchSystem: MatchSystem;
    private geo: PropSystemGeometry;

    constructor(board: Board, matchSystem: MatchSystem, geo: PropSystemGeometry) {
        this.board = board;
        this.matchSystem = matchSystem;
        this.geo = geo;
    }

    /** 关卡切换后由 LevelManager 调用，刷新当前关卡的几何参数 */
    updateGeometry(geo: PropSystemGeometry) {
        this.geo = geo;
    }

    /** 道具入口。由 HUDController.onClickBtn → 此处触发 */
    useProp(type: PropType): boolean {
        if (GameManager.instance.state !== 'playing') return false;
        if (!GameManager.instance.useProp(type)) return false;

        switch (type) {
            case 'undo':
                return this.matchSystem.undoLast();
            case 'shuffle':
                this.shuffle();
                return true;
            case 'remove':
                return this.removeTriple();
        }
        return false;
    }

    /** 洗牌：normal 牌重新分配网格坐标；special 牌保持原 (gx, gy, gz) 不动；
     *  目标：保证至少一组 pattern 数 ≥ 3 且其中至少一张可点，避免"同色全堆顶、底部全被压"的死局 */
    private shuffle() {
        const normals: TileData[] = [];
        const specials: TileData[] = [];
        this.board.forEachActive((t) => {
            if (t.special === 'none') normals.push(t);
            else specials.push(t);
        });
        if (normals.length === 0) return;

        // 候选网格范围：取决于 layerOffset 决定的可视区域；保守给 0..5 x 0..7，z 0..3 共 144 格
        const candidates: Array<{ gx: number; gy: number; gz: number }> = [];
        for (let z = 0; z <= 3; z++) {
            for (let y = 0; y < 8; y++) {
                for (let x = 0; x < 6; x++) {
                    candidates.push({ gx: x, gy: y, gz: z });
                }
            }
        }

        const specialsKey = (s: TileData) => `${s.gx},${s.gy},${s.gz}`;
        const sameKey = (a: { gx: number; gy: number; gz: number }) => `${a.gx},${a.gy},${a.gz}`;

        let attempts = 0;
        const MAX_ATTEMPTS = 5;
        let success = false;

        for (attempts = 0; attempts < MAX_ATTEMPTS; attempts++) {
            // Fisher-Yates 洗候选池
            for (let i = candidates.length - 1; i > 0; i--) {
                const j = Math.floor(Math.random() * (i + 1));
                [candidates[i], candidates[j]] = [candidates[j], candidates[i]];
            }

            const used = new Set<string>();
            for (const s of specials) used.add(specialsKey(s));

            // 给每个 normal 牌分配一个不冲突的坐标
            const assigned: Array<{ tile: TileData; pos: { gx: number; gy: number; gz: number } }> = [];
            let conflict = false;
            for (const t of normals) {
                const pos = candidates.find((c) => !used.has(sameKey(c)));
                if (!pos) {
                    conflict = true;
                    break;
                }
                used.add(sameKey(pos));
                assigned.push({ tile: t, pos });
            }
            if (conflict) continue;

            // 可行性检测：场上至少有一个 pattern 数量 ≥ 3 且该组至少一张牌的 gz 是该 pattern 里的最大值
            if (this.isLayoutViable(assigned)) {
                // 提交坐标 + 启动 tween
                for (const { tile, pos } of assigned) {
                    tile.gx = pos.gx;
                    tile.gy = pos.gy;
                    tile.gz = pos.gz;
                    const node = tile.node;
                    Tween.stopAllByTarget(node);
                    const target = this.board.gridToWorld(
                        pos.gx, pos.gy, pos.gz,
                        this.geo.origin, this.geo.cellWidth, this.geo.cellHeight, this.geo.layerOffset,
                    );
                    (node as any).originalPos = target.clone();
                    Tween.get(node)
                        .to(0.3, { position: target })
                        .start();
                }
                success = true;
                break;
            }
        }

        if (!success) {
            console.warn('[PropSystem] shuffle failed to find viable layout, refunding');
            GameManager.instance.refundProp('shuffle');
        }
    }

    /** 检测当前分配是否至少产生一组可点的三消：
     *  - 同 pattern 的 normal 牌数 ≥ 3
     *  - 这组牌里至少有一张 gz 是同组中最大的（保证上方没牌遮挡，能被点击） */
    private isLayoutViable(
        assigned: Array<{ tile: TileData; pos: { gx: number; gy: number; gz: number } }>,
    ): boolean {
        // 构造 pattern → gz 列表（仅看本次被分配的 normal）
        const byPattern = new Map<number, number[]>();
        for (const { tile, pos } of assigned) {
            const arr = byPattern.get(tile.pattern) ?? [];
            arr.push(pos.gz);
            byPattern.set(tile.pattern, arr);
        }
        for (const [, gzs] of byPattern) {
            if (gzs.length < 3) continue;
            const maxGz = Math.max(...gzs);
            // 至少一张牌占据了该 pattern 当前最高的 z，意味着正上方没有同组遮挡
            if (gzs.filter((z) => z === maxGz).length > 0) return true;
        }
        return false;
    }

    /** 移出：扫描场上 normal 牌同 pattern 数量 ≥ 3 的，消除前 3 张 */
    private removeTriple(): boolean {
        const counts = new Map<number, TileData[]>();
        this.board.forEachActive((t) => {
            if (t.special !== 'none') return;
            const arr = counts.get(t.pattern) ?? [];
            arr.push(t);
            counts.set(t.pattern, arr);
        });

        for (const arr of counts.values()) {
            if (arr.length >= 3) {
                const triple = arr.slice(0, 3);
                for (const t of triple) {
                    const tileComp = t.node.getComponent(Tile);
                    if (tileComp) {
                        tileComp.playRemoveAnim(() => this.board.releaseTileNode(t.node));
                    } else {
                        this.board.releaseTileNode(t.node);
                    }
                }
                if (this.board.isCleared()) {
                    GameManager.instance.completeLevel();
                }
                return true;
            }
        }
        return false;
    }
}