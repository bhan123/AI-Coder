/**
 * 本地持久化封装。微信小游戏运行时会替换 localStorage 为 wx.setStorageSync，
 * 这里统一通过 try/catch 兜底，避免编辑器/浏览器环境报错。
 */

export class Storage {
    static set<T = any>(key: string, value: T): boolean {
        try {
            localStorage.setItem(key, JSON.stringify(value));
            return true;
        } catch (e) {
            console.warn('[Storage] set failed', key, e);
            return false;
        }
    }

    static get<T = any>(key: string, defaultValue?: T): T | undefined {
        try {
            const raw = localStorage.getItem(key);
            if (raw == null) return defaultValue;
            return JSON.parse(raw) as T;
        } catch {
            return defaultValue;
        }
    }

    static remove(key: string): void {
        try {
            localStorage.removeItem(key);
        } catch (e) {
            console.warn('[Storage] remove failed', key, e);
        }
    }
}

/** 持久化的 key 常量 */
export const StorageKey = {
    BestScore: 'game.best_score',
    UnlockedLevel: 'game.unlocked_level',
    Settings: 'game.settings',
} as const;
