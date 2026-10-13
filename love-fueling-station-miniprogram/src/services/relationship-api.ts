import { getStorageSync, setStorageSync } from '@tarojs/taro';
import { cloudEnvironmentId, operationsFunctionName, relationshipFunctionName } from '../config/cloudbase';
import { RelationshipState } from '../domain/relationship';
import {
  parseApiEnvelope,
  parseCloudConnection,
  parseCloudRecordPage,
  parseObject,
  parsePrivacyExport,
  parseText,
  ParsedCloudConnection,
  ParsedPrivacyExport,
  ParsedRecordPage,
} from './relationship-contract';

declare const wx: {
  requestSubscribeMessage?: (options: { tmplIds: string[] }) => Promise<Record<string, string>>;
  cloud?: {
    init: (options: { env: string; traceUser?: boolean }) => void;
    callFunction: (options: { name: string; data: unknown }) => Promise<{ result: unknown }>;
    getTempFileURL: (options: { fileList: string[] }) => Promise<{ fileList: Array<{ fileID: string; tempFileURL?: string; status: number; errMsg?: string }> }>;
    uploadFile: (options: { cloudPath: string; filePath: string }) => Promise<{ fileID: string }>;
  };
};

export type CloudProfile = { userId: string; displayName: string };
export type CloudConnection = ParsedCloudConnection;
export type CloudRecordPage = ParsedRecordPage;
export type PrivacyNoticeStatus = { version: string; required: boolean };
export type CloudSnapshot = {
  profile: CloudProfile;
  connection: CloudConnection;
  state: RelationshipState;
  hasMoreRecords: boolean;
  nextRecordCursor: string | null;
  privacyNotice: PrivacyNoticeStatus;
};
export type PrivacyExport = ParsedPrivacyExport;
export type PrivacyExportSegment = { exportedAt: string; snapshotAt: string; segment: { authoredRecords: Record<string, unknown>[]; contributions: Record<string, unknown>[] }; nextCursor: string | null };

const MUTATION_STORAGE_KEY = 'love-fueling-station-pending-mutations-v1';
export const PRIVACY_NOTICE_VERSION = '2026-08-20-v1';

function cloudClient() {
  if (!cloudEnvironmentId || typeof wx === 'undefined' || !wx.cloud) return null;
  return wx.cloud;
}

export function isCloudConfigured() { return cloudClient() !== null; }
export function initializeCloud() {
  const cloud = cloudClient();
  if (!cloud) return false;
  cloud.init({ env: cloudEnvironmentId, traceUser: true });
  return true;
}

async function callApi(action: string, payload: Record<string, unknown> = {}): Promise<unknown> {
  const cloud = cloudClient();
  if (!cloud) throw new Error('CloudBase 尚未配置。');
  const response = await cloud.callFunction({ name: relationshipFunctionName, data: { action, ...payload } });
  return parseApiEnvelope(response.result);
}

export async function loadOperationsMetrics() {
  const cloud = cloudClient();
  if (!cloud) throw new Error('CloudBase 尚未配置。');
  const response = await cloud.callFunction({ name: operationsFunctionName, data: { action: 'summary' } });
  const raw = parseObject(parseApiEnvelope(response.result), '运营指标');
  const keys = ['activeCouples', 'relationshipRecords', 'pendingNotifications', 'notificationAttention', 'privacyCleanupBacklog'] as const;
  const metrics: Record<(typeof keys)[number], number> = { activeCouples: 0, relationshipRecords: 0, pendingNotifications: 0, notificationAttention: 0, privacyCleanupBacklog: 0 };
  for (const key of keys) {
    if (!Number.isInteger(raw[key]) || (raw[key] as number) < 0) throw new Error('运营指标格式不正确。');
    metrics[key] = raw[key] as number;
  }
  return { ...metrics, generatedAt: parseText(raw.generatedAt, '指标生成时间') };
}

function pendingMutations(): Record<string, string> {
  const stored = getStorageSync(MUTATION_STORAGE_KEY);
  return stored && typeof stored === 'object' && !Array.isArray(stored) ? stored as Record<string, string> : {};
}

function mutationFingerprint(action: string, payload: Record<string, unknown>) {
  return `${action}:${JSON.stringify(payload)}`;
}

function mutationId(action: string, payload: Record<string, unknown>) {
  const pending = pendingMutations();
  const fingerprint = mutationFingerprint(action, payload);
  if (!pending[fingerprint]) {
    pending[fingerprint] = `op-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setStorageSync(MUTATION_STORAGE_KEY, pending);
  }
  return { fingerprint, id: pending[fingerprint] };
}

function clearMutation(fingerprint: string) {
  const pending = pendingMutations();
  delete pending[fingerprint];
  setStorageSync(MUTATION_STORAGE_KEY, pending);
}

async function mutate(action: string, payload: Record<string, unknown> = {}) {
  const operation = mutationId(action, payload);
  const data = await callApi(action, { ...payload, operationId: operation.id });
  clearMutation(operation.fingerprint);
  return data;
}

function profile(value: unknown): CloudProfile {
  const raw = parseObject(value, '用户资料');
  return { userId: parseText(raw.userId, '用户 ID'), displayName: parseText(raw.displayName, '用户称呼') };
}

function connection(value: unknown): CloudConnection {
  return parseCloudConnection(value);
}

function bootstrap(value: unknown) {
  const raw = parseObject(value, '启动数据');
  const notice = parseObject(raw.privacyNotice, '隐私说明状态');
  if (typeof notice.required !== 'boolean') throw new Error('隐私说明状态无效。');
  return {
    profile: profile(raw.profile),
    connection: connection(raw.connection),
    privacyNotice: { version: parseText(notice.version, '隐私说明版本'), required: notice.required },
  };
}

function settings(value: unknown) {
  const raw = parseObject(value, '共同空间设置');
  if (!Number.isInteger(raw.score) || (raw.score as number) < 0 || (raw.score as number) > 100) throw new Error('共同分数格式无效。');
  return { score: raw.score as number };
}

function invite(value: unknown) {
  const raw = parseObject(value, '邀请结果');
  return { inviteCode: parseText(raw.inviteCode, '邀请码'), expiresAt: parseText(raw.expiresAt, '邀请有效期') };
}
function invitePreview(value: unknown) {
  const raw = parseObject(value, '邀请初始分数');
  if (!Number.isInteger(raw.initialScore) || (raw.initialScore as number) < 0 || (raw.initialScore as number) > 100) throw new Error('邀请初始分数无效。');
  return raw.initialScore as number;
}
function miniCode(value: unknown) {
  const raw = parseObject(value, '小程序码');
  return { fileId: parseText(raw.fileId, '小程序码文件'), expiresAt: parseText(raw.expiresAt, '邀请码有效期') };
}
function privacyExportSegment(value: unknown): PrivacyExportSegment {
  const raw = parseObject(value, '分段数据导出');
  const segment = parseObject(raw.segment, '分段数据导出内容');
  if (!Array.isArray(segment.authoredRecords) || !Array.isArray(segment.contributions)) throw new Error('分段数据导出格式不正确。');
  if (raw.nextCursor !== null && typeof raw.nextCursor !== 'string') throw new Error('分段数据导出游标无效。');
  return {
    exportedAt: parseText(raw.exportedAt, '分段导出时间'), snapshotAt: parseText(raw.snapshotAt, '分段导出快照时间'),
    segment: { authoredRecords: segment.authoredRecords.map((item) => parseObject(item, '本人记录')), contributions: segment.contributions.map((item) => parseObject(item, '本人贡献')) },
    nextCursor: raw.nextCursor as string | null,
  };
}

export async function resolveCloudFileUrl(fileId: string) {
  const cloud = cloudClient();
  if (!cloud) throw new Error('CloudBase 尚未配置。');
  const result = await cloud.getTempFileURL({ fileList: [fileId] });
  const item = result.fileList[0];
  if (!item || item.status !== 0 || !item.tempFileURL) throw new Error('暂时无法读取云端文件。');
  return item.tempFileURL;
}

export async function requestPartnerNotification(templateId: string) {
  if (!templateId.trim()) throw new Error('提醒模板尚未配置。');
  if (typeof wx === 'undefined' || !wx.requestSubscribeMessage) throw new Error('当前微信版本暂不支持订阅提醒。');
  // 微信要求该 API 直接由用户点击触发；调用前不要 await 任何异步操作。
  const decision = await wx.requestSubscribeMessage({ tmplIds: [templateId] });
  if (decision[templateId] !== 'accept') return { accepted: false };
  await cloudRelationshipApi.recordSubscriptionGrant(templateId);
  return { accepted: true };
}

async function mediaUploadTicket() {
  const raw = parseObject(await mutate('prepareMediaUpload'), '附件上传凭证');
  const ticketId = parseText(raw.ticketId, '附件上传凭证');
  const cloudPathPrefix = parseText(raw.cloudPathPrefix, '附件上传路径');
  return { ticketId, cloudPathPrefix };
}

export async function uploadRecordAttachments(localPaths: string[]) {
  if (localPaths.length === 0) return { uploadTicketId: undefined, attachments: [] as Array<{ fileId: string }> };
  if (localPaths.length > 3) throw new Error('一次最多添加三张照片。');
  const cloud = cloudClient();
  if (!cloud) throw new Error('CloudBase 尚未配置。');
  const ticket = await mediaUploadTicket();
  const fileIds = await Promise.all(localPaths.map(async (filePath, index) => {
    const uploaded = await cloud.uploadFile({ cloudPath: `${ticket.cloudPathPrefix}/${index}.jpg`, filePath });
    return uploaded.fileID;
  }));
  await cloudRelationshipApi.registerMediaUploadFiles(ticket.ticketId, fileIds);
  return { uploadTicketId: ticket.ticketId, attachments: fileIds.map((fileId) => ({ fileId })) };
}

export async function loadCloudSnapshot(): Promise<CloudSnapshot> {
  const boot = bootstrap(await callApi('bootstrap'));
  if (boot.connection.status !== 'paired' || !boot.connection.viewerId) {
    return { ...boot, state: { schemaVersion: 2, viewerId: 'partner-a', score: 70, records: [] }, hasMoreRecords: false, nextRecordCursor: null };
  }
  if (boot.privacyNotice.required) {
    return { ...boot, state: { schemaVersion: 2, viewerId: boot.connection.viewerId, score: 70, records: [] }, hasMoreRecords: false, nextRecordCursor: null };
  }
  const [pageValue, settingsValue] = await Promise.all([
    callApi('listRecords', { cursor: null }),
    callApi('getSettings'),
  ]);
  const page = parseCloudRecordPage(pageValue);
  const currentSettings = settings(settingsValue);
  return {
    ...boot,
    state: { schemaVersion: 2, viewerId: boot.connection.viewerId, score: currentSettings.score, records: page.records },
    hasMoreRecords: page.hasMore,
    nextRecordCursor: page.nextCursor,
  };
}

export const cloudRelationshipApi = {
  updateProfile: async (displayName: string) => profile(await mutate('updateProfile', { displayName })),
  createInvite: async (displayName: string, initialScore: number) => {
    await mutate('acceptPrivacyNotice', { version: PRIVACY_NOTICE_VERSION });
    return invite(await mutate('createInvite', { displayName, initialScore }));
  },
  cancelInvite: () => mutate('cancelInvite'),
  previewInvite: async (inviteCode: string) => invitePreview(await callApi('previewInvite', { inviteCode })),
  generateInviteMiniCode: async (inviteCode: string) => miniCode(await callApi('generateInviteMiniCode', { inviteCode })),
  acceptInvite: async (inviteCode: string, displayName: string, initialScore: number) => {
    await mutate('acceptPrivacyNotice', { version: PRIVACY_NOTICE_VERSION });
    return connection(await mutate('acceptInvite', { inviteCode, displayName, initialScore }));
  },
  acceptPrivacyNotice: () => mutate('acceptPrivacyNotice', { version: PRIVACY_NOTICE_VERSION }),
  leaveSpace: () => mutate('leaveSpace'),
  listRecords: async (cursor: string | null) => parseCloudRecordPage(await callApi('listRecords', { cursor })),
  submitCare: (content: string, points: 1 | 3 | 5, uploadTicketId?: string, attachments: Array<{ fileId: string }> = []) => mutate('createRecord', { kind: 'care', content, points, uploadTicketId, attachments }),
  submitFeeling: (content: string, points: -1 | -3 | -5, uploadTicketId?: string, attachments: Array<{ fileId: string }> = []) => mutate('createRecord', { kind: 'feeling', content, points, uploadTicketId, attachments }),
  respond: (recordId: string, response: string) => mutate('respondToRecord', { recordId, response }),
  reviewCare: (recordId: string, decision: 'approved' | 'rejected', effectivePoints: 1 | 3 | 5) => mutate('reviewCare', { recordId, decision, effectivePoints }),
  proposeRule: (payload: { title: string; content: string }) => mutate('proposeRule', payload),
  confirmRule: (recordId: string, accept: boolean) => mutate('decideRule', { recordId, accept }),
  proposeScoreAdjustment: (score: number, reason: string) => mutate('proposeScoreAdjustment', { score, reason }),
  decideScoreAdjustment: (recordId: string, accept: boolean) => mutate('decideScoreAdjustment', { recordId, accept }),
  recordSubscriptionGrant: (templateId: string) => mutate('recordSubscriptionGrant', { templateId }),
  registerMediaUploadFiles: (ticketId: string, fileIds: string[]) => mutate('registerMediaUploadFiles', { ticketId, fileIds }),
  exportMyData: async () => parsePrivacyExport(await callApi('exportMyData')),
  exportMyDataSegment: async (cursor: string | null) => privacyExportSegment(await callApi('exportMyDataSegment', { cursor })),
  getPrivacyStatus: async () => {
    const raw = parseObject(await callApi('getPrivacyStatus'), '隐私请求状态');
    if (!Array.isArray(raw.requests)) throw new Error('隐私请求状态格式不正确。');
    return {
      requests: raw.requests.map((value) => {
        const item = parseObject(value, '隐私请求');
        if (item.type !== 'space_deletion') throw new Error('隐私请求类型无效。');
        return { id: parseText(item.id, '隐私请求 ID'), type: 'space_deletion' as const, createdAt: parseText(item.createdAt, '隐私请求创建时间'), expiresAt: parseText(item.expiresAt, '隐私请求失效时间') };
      }),
    };
  },
  requestPersonalDeletion: () => mutate('requestPersonalDeletion'),
  requestSpaceDeletion: () => mutate('requestSpaceDeletion'),
  confirmSpaceDeletion: (requestId: string) => mutate('confirmSpaceDeletion', { requestId }),
};
