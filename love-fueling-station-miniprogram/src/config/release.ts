import { cloudEnvironmentId } from './cloudbase';

export const releaseVersion = '0.2.0-internal';
export const releaseChannel = cloudEnvironmentId ? 'CloudBase 测试环境' : '本地体验模式';
