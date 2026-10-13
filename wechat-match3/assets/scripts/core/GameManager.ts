import { _decorator, Component, director, Node } from 'cc';
import { EventBus, GameEvent } from './EventBus';
import { Storage, StorageKey } from './Storage';
import { LevelConfig } from '../config';

const { ccclass } = _decorator;

export enum GameState {
    Idle = 'idle',
    Playing = 'playing',
    Paused = 'paused',
    GameOver = 'gameover',
    LevelComplete = 'levelcomplete',
}

export type PropType = 'undo' | 'shuffle' | 'remove';

export interface PropCounts {
    undo: number;
    shuffle: number;
    remove: number;
}

/**
 * 全局游戏管理器：单例 + 跨场景常驻。
 * 管：游戏状态机、分数、关卡进度、撤销次数、提示次数、道具次数。
 *
 * 用法：
 *   GameManager.instance.startLevel(3);
 *   GameManager.instance.score += 10;
 *   GameManager.instance.useHint();
 *   GameManager.instance.useProp('undo');
 */
@ccclass('GameManager')
export class GameManager extends Component {
    private static _instance: GameManager | null = null;

    public static get instance(): GameManager {
        if (!GameManager._instance) {
            console.warn('[GameManager] 还未初始化，请先在场景中挂载 GameManager 节点');
        }
        return GameManager._instance as GameManager;
    }

    public state: GameState = GameState.Idle;
    public score: number = 0;
    public currentLevel: number = 1;
    public undoCount: number = 3;
    public maxUndo: number = 3;
    public hintCount: number = 3;
    public maxHint: number = 3;
    public propCounts: PropCounts = { undo: 3, shuffle: 3, remove: 3 };
    public maxProp: PropCounts = { undo: 3, shuffle: 3, remove: 3 };
    public rescueCount: number = 0;
    public maxRescuePerLevel: number = LevelConfig.maxRescuePerLevel;

    onLoad() {
        if (GameManager._instance && GameManager._instance !== this) {
            this.destroy();
            return;
        }
        GameManager._instance = this;
        director.addPersistRootNode(this.node);
    }

    onDestroy() {
        if (GameManager._instance === this) GameManager._instance = null;
    }

    /** 开始一关 */
    startLevel(levelId: number) {
        this.currentLevel = levelId;
        this.score = 0;
        this.undoCount = this.maxUndo;
        this.hintCount = this.maxHint;
        this.propCounts = { ...this.maxProp };
        this.rescueCount = 0;
        this.state = GameState.Playing;
        EventBus.emit(GameEvent.ScoreChanged, this.score);
        EventBus.emit(GameEvent.UndoCountChanged, this.undoCount);
        EventBus.emit(GameEvent.HintCountChanged, this.hintCount);
        EventBus.emit(GameEvent.PropCountChanged, { ...this.propCounts });
    }

    addScore(delta: number) {
        this.score += delta;
        EventBus.emit(GameEvent.ScoreChanged, this.score);

        const best = Storage.get<number>(StorageKey.BestScore, 0) ?? 0;
        if (this.score > best) Storage.set(StorageKey.BestScore, this.score);
    }

    /** 通关：解锁下一关 + 持久化 */
    completeLevel() {
        this.state = GameState.LevelComplete;
        const unlocked = Storage.get<number>(StorageKey.UnlockedLevel, 1) ?? 1;
        const nextLevel = this.currentLevel + 1;
        if (nextLevel > unlocked) {
            Storage.set(StorageKey.UnlockedLevel, nextLevel);
        }
        EventBus.emit(GameEvent.LevelComplete, this.currentLevel, this.score);
    }

    failLevel() {
        this.state = GameState.GameOver;
        EventBus.emit(GameEvent.LevelFailed, this.currentLevel, this.score);
    }

    togglePause() {
        if (this.state === GameState.Playing) {
            this.state = GameState.Paused;
            director.pause();
        } else if (this.state === GameState.Paused) {
            this.state = GameState.Playing;
            director.resume();
        }
        EventBus.emit(GameEvent.PauseToggled, this.state === GameState.Paused);
    }

    /** 消耗一次提示次数；返回是否成功 */
    useHint(): boolean {
        if (this.hintCount <= 0) return false;
        this.hintCount -= 1;
        EventBus.emit(GameEvent.HintCountChanged, this.hintCount);
        return true;
    }

    /** 消耗一次道具；返回是否成功。真正的道具效果由调用方（PropSystem）触发 */
    useProp(type: PropType): boolean {
        if (this.propCounts[type] <= 0) return false;
        this.propCounts[type] -= 1;
        EventBus.emit(GameEvent.PropCountChanged, { ...this.propCounts });
        return true;
    }

    /** 退还一次道具（仅在道具执行失败时使用，避免白白扣费） */
    refundProp(type: PropType): void {
        this.propCounts[type] = Math.min(this.propCounts[type] + 1, this.maxProp[type]);
        EventBus.emit(GameEvent.PropCountChanged, { ...this.propCounts });
    }

    /**
     * 视频复活：清空 slot + 重置状态为 playing + 计数 +1
     * 返回 true 表示复活成功，false 表示已达上限或场上没牌可继续
     */
    rescueFromAd(): boolean {
        if (this.rescueCount >= this.maxRescuePerLevel) return false;
        if (this.state !== GameState.GameOver) return false;
        this.rescueCount += 1;
        this.state = GameState.Playing;
        EventBus.emit(GameEvent.AdRescue, this.rescueCount);
        return true;
    }
}