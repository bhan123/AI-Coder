import { _decorator, Button, Component, Label, Node } from 'cc';
import { EventBus, GameEvent } from '../core/EventBus';
import { AudioManager, SfxName } from '../core/AudioManager';

const { ccclass, property } = _decorator;

type Callback = () => void;

/**
 * 弹窗控制器：通关 / 失败 / 暂停三个弹窗。
 *
 * 三个弹窗节点作为 DialogController 节点的子节点，由用户在场景编辑器里搭建。
 * 本脚本只引用顶层 Node + 关键 Button + Label，弹窗内部结构由 UI 自行组装。
 *
 * 回调通过 show*() 注入，按钮触发后自动 hideAll()，避免上层忘记关弹窗。
 */
@ccclass('DialogController')
export class DialogController extends Component {
    @property(Node)
    public levelCompleteDialog: Node | null = null;

    @property(Node)
    public levelFailedDialog: Node | null = null;

    @property(Node)
    public pauseDialog: Node | null = null;

    // 通关弹窗
    @property(Label)
    public completeLevelLabel: Label | null = null;

    @property(Label)
    public completeScoreLabel: Label | null = null;

    @property(Button)
    public nextBtn: Button | null = null;

    @property(Button)
    public shareBtn: Button | null = null;

    @property(Button)
    public completeCloseBtn: Button | null = null;

    // 失败弹窗
    @property(Label)
    public failedLevelLabel: Label | null = null;

    @property(Label)
    public failedScoreLabel: Label | null = null;

    @property(Button)
    public retryBtn: Button | null = null;

    @property(Button)
    public shareRescueBtn: Button | null = null;

    @property(Button)
    public rewardAdBtn: Button | null = null;

    @property(Button)
    public failedCloseBtn: Button | null = null;

    // 暂停弹窗
    @property(Button)
    public resumeBtn: Button | null = null;

    @property(Button)
    public pauseRetryBtn: Button | null = null;

    @property(Button)
    public pauseCloseBtn: Button | null = null;

    // 用对象保存每组回调，避免多个弹窗互相覆盖
    private callbacks = {
        completeNext: null as Callback | null,
        completeShare: null as Callback | null,
        failedRetry: null as Callback | null,
        failedShareRescue: null as Callback | null,
        failedRewardAd: null as Callback | null,
        pauseResume: null as Callback | null,
        pauseRetry: null as Callback | null,
    };

    onLoad() {
        this.hideAll();
        this.bindButtons();
    }

    /**
     * 按钮 click → playSFX → 调用回调 → hideAll。
     * 统一封装避免每个 click 处理都重复 playSFX+hideAll。
     * 注意：Cocos Button 的 on() 是累加绑定，所以每次调用 bindButton 前先 off。
     */
    private bindButton(btn: Button | null, cb: Callback | null) {
        if (!btn) return;
        // 先解绑上一次绑的同一回调，避免重复 click 触发多次
        btn.node.off(Button.EventType.CLICK, this.dispatchButtonClick, this);
        if (!cb) return;
        btn.node.on(Button.EventType.CLICK, this.dispatchButtonClick, this);
    }

    /**
     * click 派发器：每次都用当前 btn 反查对应回调，避免在 click handler 闭包里捕获过时的 cb。
     */
    private dispatchButtonClick = (event: any) => {
        const node = (event?.currentTarget ?? event?.target) as Node;
        AudioManager.instance?.playSFX(SfxName.Click);
        this.hideAll();
        // 解析点击的是哪个按钮
        let cb: Callback | null = null;
        if (node === this.nextBtn?.node) cb = this.callbacks.completeNext;
        else if (node === this.shareBtn?.node) cb = this.callbacks.completeShare;
        else if (node === this.completeCloseBtn?.node) cb = this.callbacks.completeNext;
        else if (node === this.retryBtn?.node) cb = this.callbacks.failedRetry;
        else if (node === this.shareRescueBtn?.node) cb = this.callbacks.failedShareRescue;
        else if (node === this.rewardAdBtn?.node) cb = this.callbacks.failedRewardAd;
        else if (node === this.failedCloseBtn?.node) { /* failedCloseBtn 只是 X 关闭，不调业务回调 */ }
        else if (node === this.resumeBtn?.node) cb = this.callbacks.pauseResume;
        else if (node === this.pauseRetryBtn?.node) cb = this.callbacks.pauseRetry;
        else if (node === this.pauseCloseBtn?.node) cb = this.callbacks.pauseResume;
        if (cb) cb();
    };

    private bindButtons() {
        // 通关
        this.bindButton(this.nextBtn, this.callbacks.completeNext);
        this.bindButton(this.shareBtn, this.callbacks.completeShare);
        this.bindButton(this.completeCloseBtn, this.callbacks.completeNext); // 关闭当作"知道了"

        // 失败
        this.bindButton(this.retryBtn, this.callbacks.failedRetry);
        this.bindButton(this.shareRescueBtn, this.callbacks.failedShareRescue);
        this.bindButton(this.rewardAdBtn, this.callbacks.failedRewardAd);
        this.bindButton(this.failedCloseBtn, null); // 关闭由 hideAll 处理

        // 暂停
        this.bindButton(this.resumeBtn, this.callbacks.pauseResume);
        this.bindButton(this.pauseRetryBtn, this.callbacks.pauseRetry);
        this.bindButton(this.pauseCloseBtn, this.callbacks.pauseResume); // 关闭当作"恢复"
    }

    showLevelComplete(levelId: number, score: number, onNext: Callback, onShare: Callback) {
        this.hideAll();
        if (this.completeLevelLabel) this.completeLevelLabel.string = `第 ${levelId} 关 通关！`;
        if (this.completeScoreLabel) this.completeScoreLabel.string = `分数 ${score}`;
        this.callbacks.completeNext = onNext;
        this.callbacks.completeShare = onShare;
        this.bindButtons(); // 重新绑定以注入新回调
        if (this.levelCompleteDialog) this.levelCompleteDialog.active = true;
        EventBus.emit(GameEvent.DialogShow, 'levelComplete');
    }

    showLevelFailed(levelId: number, score: number, onRetry: Callback, onShareRescue: Callback, onRewardAd: Callback) {
        this.hideAll();
        if (this.failedLevelLabel) this.failedLevelLabel.string = `第 ${levelId} 关 失败`;
        if (this.failedScoreLabel) this.failedScoreLabel.string = `分数 ${score}`;
        this.callbacks.failedRetry = onRetry;
        this.callbacks.failedShareRescue = onShareRescue;
        this.callbacks.failedRewardAd = onRewardAd;
        this.bindButtons();
        if (this.levelFailedDialog) this.levelFailedDialog.active = true;
        EventBus.emit(GameEvent.DialogShow, 'levelFailed');
    }

    showPause(onResume: Callback, onRetry: Callback) {
        this.hideAll();
        this.callbacks.pauseResume = onResume;
        this.callbacks.pauseRetry = onRetry;
        this.bindButtons();
        if (this.pauseDialog) this.pauseDialog.active = true;
        EventBus.emit(GameEvent.DialogShow, 'pause');
    }

    hideAll() {
        if (this.levelCompleteDialog) this.levelCompleteDialog.active = false;
        if (this.levelFailedDialog) this.levelFailedDialog.active = false;
        if (this.pauseDialog) this.pauseDialog.active = false;
        EventBus.emit(GameEvent.DialogHide);
    }
}
