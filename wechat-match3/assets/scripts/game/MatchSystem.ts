import { Node, Tween, UIOpacity, Vec3 } from 'cc';
import { AudioManager, SfxName } from '../core/AudioManager';
import { EventBus, GameEvent } from '../core/EventBus';
import { GameManager } from '../core/GameManager';
import { Board } from './Board';
import { Tile, TileData } from './Tile';

export interface MatchSystemOptions {
    slotCapacity?: number;        // 槽位上限（默认 7）
    slotRowGap?: number;          // 槽位节点间距（默认 90）
    slotAnchor?: Vec3;            // 槽位起点（世界坐标）
}

/**
 * 匹配系统：
 * 1. 玩家点击牌 → Board 判定可点击 → 加入 slot
 * 2. slot 凑齐 3 张（含 wild 替补）→ 触发消除
 * 3. 若消除项含 bomb → 场上所有同 pattern 的 normal 牌一并消除
 * 4. slot 满 → 失败
 * 5. Board 清空 → 通关
 *
 * 视觉：
 * - 加入 slot 时，Tile 节点从原位置 Tween 到槽位坐标
 * - 消除时，Tile 节点缩小+淡出
 */
export class MatchSystem {
    private board: Board;
    private opts: Required<MatchSystemOptions>;
    private slot: TileData[] = [];
    private slotNodes: Node[] = [];

    constructor(board: Board, opts: MatchSystemOptions = {}) {
        this.board = board;
        this.opts = {
            slotCapacity: opts.slotCapacity ?? 7,
            slotRowGap: opts.slotRowGap ?? 90,
            slotAnchor: opts.slotAnchor ?? new Vec3(-270, -360, 0),
        };
    }

    /** 玩家点击一张牌：核心入口 */
    onTap(tile: TileData) {
        if (!this.board.isClickable(tile)) return;
        if (this.slot.includes(tile)) return;
        if (GameManager.instance.state !== 'playing') return;

        // bomb 提前引爆：slot 容量所剩无几时不再挤占名额，避免凑齐 3 张的判断失效
        if (tile.special === 'bomb' && this.slot.length >= this.opts.slotCapacity - 1) {
            this.detonateBombImmediate(tile);
            return;
        }

        this.slot.push(tile);
        this.slotNodes.push(tile.node);

        AudioManager.instance.playSFX(SfxName.AddToSlot);
        this.flyToSlot(tile);
        EventBus.emit(GameEvent.TileSelected, tile, this.slot.length);

        // 三消检测
        if (this.slot.length >= 3) {
            const triple = this.findTriple();
            if (triple) {
                this.removeTriples(triple);
                return;
            }
        }

        // 槽位满了
        if (this.slot.length >= this.opts.slotCapacity) {
            AudioManager.instance.playSFX(SfxName.SlotFull);
            GameManager.instance.failLevel();
        }
    }

    /**
     * bomb 提前引爆：不进 slot，立即清除自身 + 场上所有同 pattern 的 normal 牌，
     * 适用于 slot 容量紧张或孤 bomb 场景（避免单张 bomb 卡死游戏节奏）。
     */
    private detonateBombImmediate(bomb: TileData) {
        AudioManager.instance.playSFX(SfxName.Match);

        const cascade: TileData[] = [bomb];
        bomb.removed = true;
        // 同 pattern 连锁：只扫 normal 牌，与 findAllByPattern 语义一致
        const samePattern = this.board.findAllByPattern(bomb.pattern);
        for (const t of samePattern) {
            if (!t.removed) {
                t.removed = true;
                cascade.push(t);
            }
        }

        // 引爆奖励比普通 3 消高，鼓励玩家主动 tap bomb
        GameManager.instance.addScore(cascade.length * 10 + 50);

        for (const t of cascade) {
            const tileComp = t.node.getComponent(Tile);
            if (tileComp) {
                tileComp.playRemoveAnim(() => this.board.releaseTileNode(t.node));
            } else {
                this.board.releaseTileNode(t.node);
            }
        }

        EventBus.emit(GameEvent.BombDetonated, bomb, cascade.length);

        if (this.board.isCleared()) {
            AudioManager.instance.playSFX(SfxName.Win);
            GameManager.instance.completeLevel();
        }
    }

    /**
     * 判定 slot 里能否凑出 3 张。
     * - 全 normal：按 pattern 分组，数量 ≥ 3 即触发
     * - 含 wild：wild 可替补任意 pattern，只要某 pattern 的 normal 数 + wild 数 ≥ 3
     */
    private findTriple(): { tiles: TileData[]; pattern: number; wildsUsed: TileData[] } | null {
        const wilds: TileData[] = [];
        const groups = new Map<number, TileData[]>();
        for (const t of this.slot) {
            if (t.special === 'wild') {
                wilds.push(t);
                continue;
            }
            // bomb 在 slot 内只占 1 个名额，不参与 3 消 pattern 匹配
            // 但因为 bomb 一旦进入 slot 就会引爆（见 onTap 中的 bomb 短路），这里 bomb 不会出现在 slot
            const arr = groups.get(t.pattern) ?? [];
            arr.push(t);
            groups.set(t.pattern, arr);
        }
        // 没有任何牌
        if (groups.size === 0 && wilds.length === 0) return null;

        // 1. 先看纯 normal 是否有 ≥ 3
        for (const [pattern, arr] of groups) {
            if (arr.length >= 3) {
                return { tiles: arr.slice(0, 3), pattern, wildsUsed: [] };
            }
        }
        // 2. 用 wild 补：找一个 pattern，normal 数 + wild 数 ≥ 3
        for (const [pattern, arr] of groups) {
            const need = 3 - arr.length;
            if (need > 0 && wilds.length >= need) {
                const wildsUsed = wilds.slice(0, need);
                return { tiles: [...arr, ...wildsUsed], pattern, wildsUsed };
            }
        }
        // 3. slot 里只有 wild 和 bomb，且数量 ≥ 3 → 也算一组（用 0 号 pattern 作为虚拟 pattern）
        if (groups.size === 0 && wilds.length >= 3) {
            return { tiles: wilds.slice(0, 3), pattern: -1, wildsUsed: wilds.slice(0, 3) };
        }
        return null;
    }

    private removeTriples(triple: { tiles: TileData[]; pattern: number; wildsUsed: TileData[] }) {
        const tripleSet = new Set(triple.tiles);
        // 收集待消除：slot 中的 triple 部分 + 场上同 pattern 的 normal 牌（bomb 触发）
        let cascade: TileData[] = [...triple.tiles];
        let hasBomb = triple.tiles.some((t) => t.special === 'bomb');
        if (hasBomb && triple.pattern >= 0) {
            const more = this.board.findAllByPattern(triple.pattern);
            for (const m of more) {
                if (!tripleSet.has(m)) cascade.push(m);
            }
        }

        // 从 slot 里过滤掉所有参与消除的
        const remaining: TileData[] = [];
        const remainingNodes: Node[] = [];
        for (let i = 0; i < this.slot.length; i++) {
            if (!tripleSet.has(this.slot[i])) {
                remaining.push(this.slot[i]);
                remainingNodes.push(this.slotNodes[i]);
            }
        }
        this.slot = remaining;
        this.slotNodes = remainingNodes;

        AudioManager.instance.playSFX(SfxName.Match);
        // bomb 触发额外消除给更高分；与 detonateBombImmediate 的奖励金额对齐
        const bombBonus = hasBomb ? 50 : 0;
        const scoreDelta = cascade.length * 10 + bombBonus;
        GameManager.instance.addScore(scoreDelta);

        // 动画 + 释放
        for (const t of cascade) {
            const tileComp = t.node.getComponent(Tile);
            if (tileComp) {
                tileComp.playRemoveAnim(() => this.board.releaseTileNode(t.node));
            } else {
                this.board.releaseTileNode(t.node);
            }
        }

        EventBus.emit(GameEvent.TileRemoved, cascade);
        // 重新布局剩余槽位
        this.relayoutSlot();

        // 通关判定
        if (this.board.isCleared()) {
            AudioManager.instance.playSFX(SfxName.Win);
            GameManager.instance.completeLevel();
        }
    }

    private flyToSlot(t: TileData) {
        const slotIndex = this.slotNodes.length - 1;
        const target = new Vec3(
            this.opts.slotAnchor.x + slotIndex * this.opts.slotRowGap,
            this.opts.slotAnchor.y,
            0,
        );
        Tween.stopAllByTarget(t.node);
        Tween.get(t.node)
            .to(0.2, { position: target, scale: new Vec3(0.7, 0.7, 1) })
            .start();
    }

    private relayoutSlot() {
        for (let i = 0; i < this.slot.length; i++) {
            const node = this.slotNodes[i];
            const target = new Vec3(
                this.opts.slotAnchor.x + i * this.opts.slotRowGap,
                this.opts.slotAnchor.y,
                0,
            );
            Tween.stopAllByTarget(node);
            Tween.get(node)
                .to(0.15, { position: target })
                .start();
        }
    }

    /** 撤销一步：把最后进 slot 的那张牌飞回原位 */
    undoLast(): boolean {
        if (this.slot.length === 0) return false;
        const last = this.slot.pop()!;
        const lastNode = this.slotNodes.pop()!;
        const originalPos = (last as any).originalPos ?? lastNode.getPosition().clone();

        Tween.stopAllByTarget(lastNode);
        Tween.get(lastNode)
            .to(0.2, { position: originalPos, scale: new Vec3(1, 1, 1) })
            .start();

        AudioManager.instance.playSFX(SfxName.Undo);
        this.relayoutSlot();
        return true;
    }

    /** 重置（重新开始本关时调用） */
    reset() {
        this.slot = [];
        this.slotNodes = [];
    }

    /**
     * 强制清空 slot：视频复活用，把已 selected 的牌飞回原位但不触发失败/重置分数。
     * 与 undoLast 不同：一次性清空全部 slot，且不触发 prop / score 任何变化。
     */
    forceClearSlot(): void {
        if (this.slot.length === 0) return;
        for (let i = 0; i < this.slot.length; i++) {
            const tile = this.slot[i];
            const node = this.slotNodes[i];
            const originalPos = (tile as any).originalPos ?? node.getPosition().clone();
            Tween.stopAllByTarget(node);
            Tween.get(node).to(0.2, { position: originalPos, scale: new Vec3(1, 1, 1) }).start();
        }
        this.slot = [];
        this.slotNodes = [];
    }

    /** 当前 slot 里的牌（只读快照） */
    public get slotSnapshot(): readonly TileData[] {
        return this.slot;
    }
}