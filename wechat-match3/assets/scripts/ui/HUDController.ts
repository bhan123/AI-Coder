import { _decorator, Button, Component, Label, Node } from 'cc';
import { EventBus, GameEvent } from '../core/EventBus';
import { GameManager, PropCounts, PropType } from '../core/GameManager';
import { PropSystem } from '../game/PropSystem';

const { ccclass, property } = _decorator;

/**
 * 游戏内 HUD：分数、关卡、撤销次数、暂停按钮、道具按钮。
 * 挂在一个包含 Label/Button 的 Canvas 子节点上。
 *
 * 道具入口通过外部注入 PropSystem（由 Main.ts 在 onLoad 完成后 setPropSystem）。
 */
@ccclass('HUDController')
export class HUDController extends Component {
    @property(Label)
    public scoreLabel: Label | null = null;

    @property(Label)
    public levelLabel: Label | null = null;

    @property(Label)
    public undoLabel: Label | null = null;

    @property(Button)
    public pauseBtn: Button | null = null;

    @property(Button)
    public undoBtn: Button | null = null;

    @property(Label)
    public undoCountLabel: Label | null = null;

    @property(Button)
    public shuffleBtn: Button | null = null;

    @property(Label)
    public shuffleCountLabel: Label | null = null;

    @property(Button)
    public removeBtn: Button | null = null;

    @property(Label)
    public removeCountLabel: Label | null = null;

    private propSystem: PropSystem | null = null;

    /** 由 Main.ts 注入 PropSystem 实例 */
    setPropSystem(ps: PropSystem | null) {
        this.propSystem = ps;
    }

    onLoad() {
        EventBus.on(GameEvent.ScoreChanged, this.onScore, this);
        EventBus.on(GameEvent.UndoCountChanged, this.onUndo, this);
        EventBus.on(GameEvent.PropCountChanged, this.onPropCount, this);

        if (this.pauseBtn) this.pauseBtn.node.on(Button.EventType.CLICK, this.onPauseClick, this);
        if (this.undoBtn) this.undoBtn.node.on(Button.EventType.CLICK, () => this.onPropClick('undo'), this);
        if (this.shuffleBtn) this.shuffleBtn.node.on(Button.EventType.CLICK, () => this.onPropClick('shuffle'), this);
        if (this.removeBtn) this.removeBtn.node.on(Button.EventType.CLICK, () => this.onPropClick('remove'), this);

        // 初始化 label
        const pc = GameManager.instance.propCounts;
        this.onPropCount({ ...pc });
    }

    onDestroy() {
        EventBus.off(GameEvent.ScoreChanged, this.onScore, this);
        EventBus.off(GameEvent.UndoCountChanged, this.onUndo, this);
        EventBus.off(GameEvent.PropCountChanged, this.onPropCount, this);
    }

    private onScore(score: number) {
        if (this.scoreLabel) this.scoreLabel.string = `${score}`;
    }

    private onUndo(count: number) {
        if (this.undoLabel) this.undoLabel.string = `撤销 x${count}`;
    }

    private onPropCount(counts: PropCounts) {
        if (this.undoCountLabel) this.undoCountLabel.string = `x${counts.undo}`;
        if (this.shuffleCountLabel) this.shuffleCountLabel.string = `x${counts.shuffle}`;
        if (this.removeCountLabel) this.removeCountLabel.string = `x${counts.remove}`;
    }

    private onPropClick(type: PropType) {
        if (!this.propSystem) return;
        this.propSystem.useProp(type);
    }

    private onPauseClick() {
        // 只切状态；暂停弹窗由 Main.ts 监听 PauseToggled 后弹出
        GameManager.instance.togglePause();
    }
}