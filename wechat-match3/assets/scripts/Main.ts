import { _decorator, Component, director, Node, EventTouch, UITransform, Vec3 } from 'cc';
import { Board } from './game/Board';
import { LevelManager } from './game/LevelManager';
import { MatchSystem } from './game/MatchSystem';
import { HintController } from './game/HintController';
import { AudioManager, SfxName } from './core/AudioManager';
import { EventBus, GameEvent } from './core/EventBus';
import { GameManager } from './core/GameManager';
import { WxApi } from './platform/WxApi';
import { WxConfig } from './config';
import { HUDController } from './ui/HUDController';
import { DialogController } from './ui/DialogController';

const { ccclass, property } = _decorator;

/**
 * 游戏场景入口：
 * - 在 start 完成初始化 GameManager / AudioManager 节点
 * - 监听全局点击事件 → 转发到 Board.hitTest → MatchSystem.onTap
 * - 监听长按 → HintController
 * - 监听通关/失败/暂停事件，由 DialogController 弹出对应弹窗
 */
@ccclass('Main')
export class Main extends Component {
    @property(Node)
    public gameManagerNode: Node | null = null;

    @property(Node)
    public audioManagerNode: Node | null = null;

    @property(Board)
    public board: Board | null = null;

    @property(LevelManager)
    public levelManager: LevelManager | null = null;

    @property(HUDController)
    public hud: HUDController | null = null;

    @property(HintController)
    public hintController: HintController | null = null;

    @property(DialogController)
    public dialog: DialogController | null = null;

    @property(Node)
    public boardHitArea: Node | null = null;   // 接收点击的节点（通常是 BoardRoot 自身）

    start() {
        // 1. 启动 GameManager
        if (this.gameManagerNode && !this.gameManagerNode.getComponent(GameManager)) {
            this.gameManagerNode.addComponent(GameManager);
        }
        GameManager.instance.startLevel(1);

        // 2. 启动 AudioManager
        if (this.audioManagerNode && !this.audioManagerNode.getComponent(AudioManager)) {
            this.audioManagerNode.addComponent(AudioManager);
        }
        AudioManager.instance.playBGM();

        // 3. 微信侧：打开分享菜单
        WxApi.showShareMenu();

        // 4. 加载关卡
        if (this.levelManager) {
            this.levelManager.loadLevel(1).then(() => {
                this.bindTouch();
                this.injectPropSystem();
            });
        }

        // 5. 通关 / 失败 / 暂停监听
        EventBus.on(GameEvent.LevelComplete, this.onLevelComplete, this);
        EventBus.on(GameEvent.LevelFailed, this.onLevelFailed, this);
        EventBus.on(GameEvent.PauseToggled, this.onPauseToggled, this);
    }

    onDestroy() {
        EventBus.off(GameEvent.LevelComplete, this.onLevelComplete, this);
        EventBus.off(GameEvent.LevelFailed, this.onLevelFailed, this);
        EventBus.off(GameEvent.PauseToggled, this.onPauseToggled, this);
    }

    /** 把 LevelManager.propSystem 注入 HUDController（避免 HUD 反向依赖 LevelManager） */
    private injectPropSystem() {
        if (this.hud && this.levelManager?.propSystem) {
            this.hud.setPropSystem(this.levelManager.propSystem);
        }
    }

    private bindTouch() {
        if (!this.boardHitArea || !this.board || !this.levelManager) return;
        this.boardHitArea.on(Node.EventType.TOUCH_END, this.onTouchEnd, this);
    }

    private onTouchEnd(e: EventTouch) {
        if (!this.board || !this.levelManager?.matchSystem) return;
        const ui = this.boardHitArea!.getComponent(UITransform);
        if (!ui) return;
        const worldPos = ui.convertToWorldSpaceAR(new Vec3(e.getUILocation().x, e.getUILocation().y, 0));
        const tile = this.board.hitTest(worldPos);
        if (tile) {
            WxApi.vibrateShort('light');
            AudioManager.instance.playSFX(SfxName.Click);
            this.levelManager.matchSystem.onTap(tile);
        }
    }

    private onLevelComplete(levelId: number, score: number) {
        WxApi.vibrateLong();
        AudioManager.instance.playSFX(SfxName.Win);
        this.dialog?.showLevelComplete(
            levelId,
            score,
            () => this.goToNextLevel(),
            () => WxApi.shareAppMessage({ title: '我通关了，快来挑战！', query: `level=${levelId}` })
        );
    }

    private onLevelFailed(levelId: number, score: number) {
        WxApi.vibrateLong();
        AudioManager.instance.playSFX(SfxName.Lose);
        this.dialog?.showLevelFailed(
            levelId,
            score,
            () => this.retry(),
            () => this.shareRescue(),
            () => this.rewardAdRescue()
        );
    }

    private onPauseToggled(paused: boolean) {
        if (!this.dialog) return;
        if (paused) {
            this.dialog.showPause(
                () => GameManager.instance.togglePause(),
                () => { this.dialog?.hideAll(); this.retry(); }
            );
        } else {
            this.dialog.hideAll();
        }
    }

    /** 进入下一关（从原 onLevelComplete 的 scheduleOnce 抽出） */
    goToNextLevel() {
        const next = GameManager.instance.currentLevel + 1;
        if (!this.levelManager) return;
        this.levelManager.unloadLevel();
        GameManager.instance.startLevel(next);
        this.levelManager.loadLevel(next).then(() => this.injectPropSystem());
    }

    /** 重新挑战当前关卡 */
    retry() {
        if (!this.levelManager) return;
        const cur = GameManager.instance.currentLevel;
        this.dialog?.hideAll();
        this.levelManager.unloadLevel();
        GameManager.instance.startLevel(cur);
        this.levelManager.loadLevel(cur).then(() => this.injectPropSystem());
    }

    /** 分享复活：微信环境调用 shareAppMessage，编辑器 no-op */
    shareRescue() {
        WxApi.shareAppMessage({
            title: WxConfig.shareRescueTitle,
            query: `rescue=${GameManager.instance.currentLevel}`,
        });
        // 简化策略：分享成功给一次复活机会（仅在微信环境有回调；这里默认直接 retry）
        // 后续可接 onShow 监听分享结果，失败则不复活
        this.retry();
    }

    /**
     * 视频复活：看完整广告 → 复活继续；中途关闭 → 重新显示失败弹窗
     */
    async rewardAdRescue() {
        if (GameManager.instance.rescueCount >= GameManager.instance.maxRescuePerLevel) {
            // 已用完复活次数，回退到 retry
            this.retry();
            return;
        }
        this.dialog?.hideAll();
        const watched = await WxApi.showRewardedAd(WxConfig.rewardAdUnitId);
        if (watched && GameManager.instance.rescueFromAd()) {
            // 复活成功：清空 slot，让玩家继续
            if (this.levelManager?.matchSystem) {
                this.levelManager.matchSystem.forceClearSlot();
            }
            return;
        }
        // 没看完或复活失败：重新显示失败弹窗
        const levelId = GameManager.instance.currentLevel;
        const score = GameManager.instance.score;
        EventBus.emit(GameEvent.AdRescueFailed);
        this.dialog?.showLevelFailed(
            levelId, score,
            () => this.retry(),
            () => this.shareRescue(),
            () => this.rewardAdRescue()
        );
    }
}
