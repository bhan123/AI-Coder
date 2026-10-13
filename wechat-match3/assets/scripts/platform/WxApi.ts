/**
 * 微信小游戏原生能力封装。
 * 在 Cocos 编辑器 / 浏览器环境下，`wx` 全局不存在，所有调用自动降级为 no-op，
 * 保证开发期不报错、上线期一键生效。
 */

declare const wx: any;
const hasWx = typeof wx !== 'undefined' && typeof wx.getSystemInfoSync === 'function';

export const WxApi = {
    isInMiniGame(): boolean {
        return hasWx;
    },

    /** 主域主动拉起分享面板（玩家点右上角菜单时也会触发） */
    shareAppMessage(opts?: { title?: string; imageUrl?: string; query?: string }): void {
        if (!hasWx) return;
        wx.shareAppMessage({
            title: opts?.title ?? '快来玩这款超休闲的小游戏！',
            imageUrl: opts?.imageUrl ?? '',
            query: opts?.query ?? '',
        });
    },

    showShareMenu(): void {
        if (!hasWx) return;
        wx.showShareMenu({ withShareTicket: true, menus: ['shareAppMessage', 'shareTimeline'] });
    },

    /** 短振动（点击反馈） */
    vibrateShort(type: 'light' | 'medium' | 'heavy' = 'light'): void {
        if (!hasWx) return;
        try {
            wx.vibrateShort({ type });
        } catch {
            /* 部分 Android 不支持 type 参数 */
            wx.vibrateShort();
        }
    },

    /** 长振动（通关 / 失败反馈） */
    vibrateLong(): void {
        if (!hasWx) return;
        wx.vibrateLong();
    },

    /** 创建 Banner 广告。返回 ad 实例，调用方负责 show/hide/destroy */
    createBannerAd(adUnitId: string, style?: { left?: number; top?: number; width?: number }): any {
        if (!hasWx || typeof wx.createBannerAd !== 'function') return null;
        const info = wx.getSystemInfoSync();
        const ad = wx.createBannerAd({
            adUnitId,
            style: {
                left: style?.left ?? 0,
                top: style?.top ?? info.screenHeight - 120,
                width: style?.width ?? 300,
            },
        });
        return ad;
    },

    /** 激励视频：完成后回调 onRewarded（看完才回调，否则不回调） */
    showRewardedAd(adUnitId: string): Promise<boolean> {
        return new Promise((resolve) => {
            if (!hasWx || typeof wx.createRewardedVideoAd !== 'function') return resolve(false);
            const ad = wx.createRewardedVideoAd({ adUnitId });
            let resolved = false;
            const done = (ok: boolean) => {
                if (resolved) return;
                resolved = true;
                resolve(ok);
            };
            ad.onClose((res: any) => done(!!(res && res.isEnded)));
            ad.onError(() => done(false));
            ad.load()
                .then(() => ad.show())
                .catch(() => done(false));
        });
    },

    /** 获取系统信息（屏幕宽高等）。非微信环境返回 web 兜底 */
    getSystemInfo(): { screenWidth: number; screenHeight: number; pixelRatio: number; platform: string } {
        if (hasWx) {
            const s = wx.getSystemInfoSync();
            return {
                screenWidth: s.screenWidth,
                screenHeight: s.screenHeight,
                pixelRatio: s.pixelRatio,
                platform: s.platform,
            };
        }
        return {
            screenWidth: typeof window !== 'undefined' ? window.innerWidth : 750,
            screenHeight: typeof window !== 'undefined' ? window.innerHeight : 1334,
            pixelRatio: typeof window !== 'undefined' ? window.devicePixelRatio : 1,
            platform: 'dev',
        };
    },
};
