import { _decorator, Component, EventTouch, Node, Tween, UIOpacity, Vec3 } from 'cc';
import { Board } from './Board';
import { TileData } from './Tile';
import { AudioManager, SfxName } from '../core/AudioManager';
import { GameManager } from '../core/GameManager';

const { ccclass, property } = _decorator;

/**
 * 长按提示：
 * - 玩家在 boardHitArea 上长按 0.5s，场上所有"当前可点击"的牌进入高亮（缩放 1.1 + 半透明脉冲）
 * - 松手后淡出，恢复原状
 * - 每次触发消耗 GameManager.hintCount 一次（GameManager 内部已 emit 事件）
 */
@ccclass('HintController')
export class HintController extends Component {
    @property(Node)
    public boardHitArea: Node | null = null;

    @property(Board)
    public board: Board | null = null;

    private pressTimer: any = null;
    private hinting: boolean = false;
    private hintTiles: TileData[] = [];

    onLoad() {
        if (this.boardHitArea) {
            this.boardHitArea.on(Node.EventType.TOUCH_START, this.onTouchStart, this);
            this.boardHitArea.on(Node.EventType.TOUCH_END, this.onTouchEnd, this);
            this.boardHitArea.on(Node.EventType.TOUCH_CANCEL, this.onTouchCancel, this);
        }
    }

    onDestroy() {
        if (this.boardHitArea) {
            this.boardHitArea.off(Node.EventType.TOUCH_START, this.onTouchStart, this);
            this.boardHitArea.off(Node.EventType.TOUCH_END, this.onTouchEnd, this);
            this.boardHitArea.off(Node.EventType.TOUCH_CANCEL, this.onTouchCancel, this);
        }
        this.clearHint();
    }

    private onTouchStart(_e: EventTouch) {
        if (this.hinting) return;
        if (GameManager.instance.state !== 'playing') return;
        this.clearPressTimer();
        this.pressTimer = this.scheduleOnce(this.triggerHint, 0.5);
    }

    private onTouchEnd(_e: EventTouch) {
        this.clearPressTimer();
        if (this.hinting) this.fadeOutHint();
    }

    private onTouchCancel(_e: EventTouch) {
        this.clearPressTimer();
        if (this.hinting) this.fadeOutHint();
    }

    private clearPressTimer() {
        if (this.pressTimer) {
            this.unschedule(this.triggerHint);
            this.pressTimer = null;
        }
    }

    private triggerHint() {
        this.pressTimer = null;
        if (!this.board) return;
        if (GameManager.instance.state !== 'playing') return;
        if (!GameManager.instance.useHint()) return;

        const tiles: TileData[] = [];
        this.board.forEachActive((t) => {
            if (this.board!.isClickable(t)) tiles.push(t);
        });
        if (tiles.length === 0) return;

        this.hintTiles = tiles;
        this.hinting = true;
        AudioManager.instance.playSFX(SfxName.Hint);

        for (const t of tiles) {
            const node = t.node;
            const op = node.getComponent(UIOpacity) ?? node.addComponent(UIOpacity);
            Tween.stopAllByTarget(node);
            Tween.stopAllByTarget(op);
            const startScale = node.getScale().clone();
            (node as any).__hintOriginalScale = startScale;

            Tween.get(node)
                .to(0.15, { scale: new Vec3(1.1, 1.1, 1) })
                .start();
            Tween.get(op)
                .to(0.6, { opacity: 120 })
                .to(0.6, { opacity: 255 })
                .union()
                .repeatForever()
                .start();
        }
    }

    private fadeOutHint() {
        if (!this.hinting) return;
        const tiles = this.hintTiles;
        this.hinting = false;
        this.hintTiles = [];

        for (const t of tiles) {
            const node = t.node;
            const op = node.getComponent(UIOpacity);
            const origScale: Vec3 = (node as any).__hintOriginalScale ?? new Vec3(1, 1, 1);
            delete (node as any).__hintOriginalScale;

            Tween.stopAllByTarget(node);
            Tween.get(node)
                .to(0.2, { scale: origScale })
                .start();
            if (op) {
                Tween.stopAllByTarget(op);
                Tween.get(op)
                    .to(0.25, { opacity: 255 })
                    .start();
            }
        }
    }

    private clearHint() {
        if (this.pressTimer) {
            this.unschedule(this.triggerHint);
            this.pressTimer = null;
        }
        if (this.hinting) this.fadeOutHint();
    }
}