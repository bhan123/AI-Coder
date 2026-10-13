/**
 * 全局事件总线。模块间解耦用，避免层层 import。
 * 例：MatchSystem 检测到通关 → EventBus.emit(GameEvent.LevelComplete) → HUDController 订阅刷新。
 */

type Handler = (...args: any[]) => void;

export class EventBus {
    private static handlers = new Map<string, Handler[]>();

    static on(event: string, handler: Handler): void {
        if (!this.handlers.has(event)) this.handlers.set(event, []);
        this.handlers.get(event)!.push(handler);
    }

    static off(event: string, handler: Handler): void {
        const list = this.handlers.get(event);
        if (!list) return;
        const idx = list.indexOf(handler);
        if (idx >= 0) list.splice(idx, 1);
    }

    static emit(event: string, ...args: any[]): void {
        const list = this.handlers.get(event);
        if (!list) return;
        // 拷贝一份再遍历，避免回调中 off 导致跳过
        const snapshot = list.slice();
        for (const h of snapshot) {
            try {
                h(...args);
            } catch (err) {
                console.error(`[EventBus] handler for "${event}" threw:`, err);
            }
        }
    }

    static clear(event?: string): void {
        if (event) this.handlers.delete(event);
        else this.handlers.clear();
    }
}

/** 全局事件名常量 */
export const GameEvent = {
    TileSelected: 'tile.selected',
    TileRemoved: 'tile.removed',
    SlotFull: 'slot.full',
    LevelComplete: 'level.complete',
    LevelFailed: 'level.failed',
    ScoreChanged: 'score.changed',
    UndoCountChanged: 'undo.changed',
    PauseToggled: 'pause.toggled',
    HintCountChanged: 'hint.changed',
    PropCountChanged: 'prop.changed',
    DialogShow: 'dialog.show',
    DialogHide: 'dialog.hide',
    BombDetonated: 'bomb.detonated',
    AdRescue: 'ad.rescue',
    AdRescueFailed: 'ad.rescue.failed',
} as const;
