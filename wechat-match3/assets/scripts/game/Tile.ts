import { _decorator, Component, Node, Sprite, SpriteFrame, UIOpacity, UITransform, Vec3 } from 'cc';
const { ccclass, property } = _decorator;

export type TileSpecial = 'none' | 'bomb' | 'wild';

export interface TileData {
    id: number;
    pattern: number;   // 图案 id（0..N）
    gx: number;
    gy: number;
    gz: number;
    node: Node;
    removed: boolean;
    special: TileSpecial;
}

/**
 * 单张牌的视图与状态。
 * - 通过 @property 注入正面/背面/高亮 spriteFrame
 * - 状态：normal / highlight（被选中）/ removing（消除动画中）
 */
@ccclass('Tile')
export class Tile extends Component {
    @property(Sprite)
    public sprite: Sprite | null = null;

    @property([SpriteFrame])
    public patternFrames: SpriteFrame[] = [];

    @property(SpriteFrame)
    public backFrame: SpriteFrame | null = null;

    @property(SpriteFrame)
    public highlightFrame: SpriteFrame | null = null;

    @property(SpriteFrame)
    public bombFrame: SpriteFrame | null = null;

    @property(SpriteFrame)
    public wildFrame: SpriteFrame | null = null;

    public data: TileData | null = null;

    /** 由 Board 在 addTile 时调用：写入 data 并刷新视图 */
    bind(data: TileData) {
        this.data = data;
        this.refresh();
    }

    refresh() {
        if (!this.data || !this.sprite) return;
        let frame: SpriteFrame | null = null;
        if (this.data.special === 'bomb' && this.bombFrame) {
            frame = this.bombFrame;
        } else if (this.data.special === 'wild' && this.wildFrame) {
            frame = this.wildFrame;
        } else {
            frame = this.patternFrames[this.data.pattern] ?? this.backFrame;
        }
        if (frame) this.sprite.spriteFrame = frame;
    }

    /** 选中态：替换 spriteFrame 为高亮图 */
    setHighlight(on: boolean) {
        if (!this.sprite) return;
        if (on && this.highlightFrame) {
            this.sprite.spriteFrame = this.highlightFrame;
        } else {
            this.refresh();
        }
    }

    /** 触发消除动画：缩小 + 淡出，结束后回调 */
    playRemoveAnim(onDone: () => void) {
        if (this.data) this.data.removed = true;
        const op = this.getComponent(UIOpacity) ?? this.addComponent(UIOpacity);
        const startScale = this.node.getScale().clone();
        const t = 0.25;
        let elapsed = 0;
        const tick = (dt: number) => {
            elapsed += dt;
            const k = Math.min(elapsed / t, 1);
            const s = 1 - k;
            this.node.setScale(startScale.x * s, startScale.y * s, startScale.z);
            op.opacity = Math.floor(255 * (1 - k));
            if (k >= 1) {
                this.unschedule(tick);
                onDone();
            }
        };
        this.schedule(tick, 0);
    }
}