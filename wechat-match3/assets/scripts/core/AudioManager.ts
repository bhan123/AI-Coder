import { _decorator, AudioClip, AudioSourceComponent, Component } from 'cc';
import { Storage, StorageKey } from './Storage';

const { ccclass, property } = _decorator;

export enum SfxName {
    Click = 'click',
    Match = 'match',
    AddToSlot = 'add_to_slot',
    SlotFull = 'slot_full',
    Win = 'win',
    Lose = 'lose',
    Undo = 'undo',
    Hint = 'hint',
}

/**
 * 音频管理器：单例。
 * 在编辑器里把 AudioClip 拖到对应的 @property 字段上即可。
 * 静音/音量设置会持久化到 Storage。
 *
 * 找 SFX 通过 AudioClip.name 匹配 SfxName 字符串。
 * 因此美术资源导入后请把 AudioClip 文件名命名为对应的 enum 值（如 click.mp3）。
 */
@ccclass('AudioManager')
export class AudioManager extends Component {
    private static _instance: AudioManager | null = null;

    public static get instance(): AudioManager {
        if (!AudioManager._instance) {
            console.warn('[AudioManager] 还未初始化');
        }
        return AudioManager._instance as AudioManager;
    }

    @property(AudioClip)
    public bgm: AudioClip | null = null;

    @property([AudioClip])
    public sfxClips: AudioClip[] = [];

    private bgmSource: AudioSourceComponent | null = null;
    private sfxSource: AudioSourceComponent | null = null;
    private sfxIndex = new Map<string, AudioClip>();

    private sfxVolume = 1;
    private bgmVolume = 0.6;
    private sfxMuted = false;
    private bgmMuted = false;

    onLoad() {
        if (AudioManager._instance && AudioManager._instance !== this) {
            this.destroy();
            return;
        }
        AudioManager._instance = this;

        const settings = Storage.get<{ sfxMuted?: boolean; bgmMuted?: boolean; sfxVolume?: number; bgmVolume?: number }>(
            StorageKey.Settings,
            {},
        );
        this.sfxMuted = settings?.sfxMuted ?? false;
        this.bgmMuted = settings?.bgmMuted ?? false;
        this.sfxVolume = settings?.sfxVolume ?? 1;
        this.bgmVolume = settings?.bgmVolume ?? 0.6;

        this.bgmSource = this.getComponent(AudioSourceComponent) || this.addComponent(AudioSourceComponent);
        this.sfxSource = this.addComponent(AudioSourceComponent);

        if (this.bgm) {
            this.bgmSource!.clip = this.bgm;
            this.bgmSource!.loop = true;
            this.bgmSource!.volume = this.bgmVolume;
        }

        for (const clip of this.sfxClips) {
            if (clip && clip.name) this.sfxIndex.set(clip.name, clip);
        }
    }

    onDestroy() {
        if (AudioManager._instance === this) AudioManager._instance = null;
    }

    playBGM() {
        if (this.bgmMuted || !this.bgmSource?.clip) return;
        this.bgmSource.play();
    }

    stopBGM() {
        this.bgmSource?.stop();
    }

    playSFX(name: SfxName) {
        if (this.sfxMuted) return;
        const clip = this.sfxIndex.get(name);
        if (!clip || !this.sfxSource) return;
        this.sfxSource.clip = clip;
        this.sfxSource.volume = this.sfxVolume;
        this.sfxSource.playOneShot(clip, this.sfxVolume);
    }

    toggleSfxMute(): boolean {
        this.sfxMuted = !this.sfxMuted;
        this.persist();
        return this.sfxMuted;
    }

    toggleBgmMute(): boolean {
        this.bgmMuted = !this.bgmMuted;
        if (this.bgmMuted) this.stopBGM();
        else this.playBGM();
        this.persist();
        return this.bgmMuted;
    }

    private persist() {
        Storage.set(StorageKey.Settings, {
            sfxMuted: this.sfxMuted,
            bgmMuted: this.bgmMuted,
            sfxVolume: this.sfxVolume,
            bgmVolume: this.bgmVolume,
        });
    }
}
