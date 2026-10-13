/**
 * 全局配置：广告位 id、分享文案、关卡参数。
 * 实际部署时把 adunit-xxx 替换成微信公众平台申请的真实广告位。
 */

export const WxConfig = {
    /** 激励视频广告位 id（失败复活用） */
    rewardAdUnitId: 'adunit-reward-placeholder',
    /** Banner 广告位 id（预留，暂未接入） */
    bannerAdUnitId: 'adunit-banner-placeholder',
    /** 通关分享文案 */
    shareWinTitle: '我通关了，快来挑战！',
    /** 失败分享复活文案 */
    shareRescueTitle: '救救我，这一关好难！',
};

export const LevelConfig = {
    /** 起始关卡（debug 时可改） */
    startLevel: 1,
    /** 每关最多视频复活次数（防止刷广告） */
    maxRescuePerLevel: 1,
};