import { PartnerId, RelationshipRecord } from '../domain/relationship';

export type ParsedRecordPage = { records: RelationshipRecord[]; hasMore: boolean; nextCursor: string | null };
export type ParsedCloudConnection =
  | { status: 'unpaired' }
  | { status: 'paired'; coupleId: string; viewerId: PartnerId }
  | { status: 'deletion_pending'; deleteAfter: string };
export type ParsedPrivacyExport = {
  exportedAt: string;
  retentionPolicy: { liveDeletionDays: number; backupDeletionDays: number };
  profile: Record<string, unknown>;
  identities: Record<string, unknown>[];
  consents: Record<string, unknown>[];
  memberships: Record<string, unknown>[];
  invites: Record<string, unknown>[];
  authoredRecords: Record<string, unknown>[];
  contributions: Record<string, unknown>[];
  auditEvents: Record<string, unknown>[];
  privacyRequests: Record<string, unknown>[];
};

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}格式不正确。`);
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string) {
  if (typeof value !== 'string' || value.length === 0) throw new Error(`${label}缺失。`);
  return value;
}

function objectArray(value: unknown, label: string) {
  if (!Array.isArray(value)) throw new Error(`${label}格式不正确。`);
  return value.map((item, index) => object(item, `${label}第${index + 1}项`));
}
function attachments(value: unknown): { fileId: string }[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value) || value.length > 3) throw new Error('记录附件格式无效。');
  return value.map((item) => ({ fileId: text(object(item, '记录附件').fileId, '附件文件') }));
}

function parseRecord(value: unknown): RelationshipRecord {
  const raw = object(value, '云端记录');
  const id = typeof raw.id === 'string' ? raw.id : typeof raw._id === 'string' ? raw._id : null;
  if (!id) throw new Error('云端记录缺少记录 ID。');
  if (raw.kind !== 'care' && raw.kind !== 'feeling' && raw.kind !== 'rule' && raw.kind !== 'score_adjustment') throw new Error('云端记录类型不受支持。');
  if (raw.authorId !== 'partner-a' && raw.authorId !== 'partner-b') throw new Error('云端记录作者无效。');
  const createdAt = text(raw.createdAt, '创建时间');
  const content = text(raw.content, '记录内容');
  const authorId: PartnerId = raw.authorId;
  const common = { id, authorId, createdAt, content, attachments: attachments(raw.attachments) };

  if (raw.kind === 'care') {
    if (raw.status !== 'pending' && raw.status !== 'approved' && raw.status !== 'rejected') throw new Error('行动记录状态无效。');
    if (raw.requestedPoints !== 1 && raw.requestedPoints !== 3 && raw.requestedPoints !== 5) throw new Error('行动申请分数无效。');
    const effectivePoints = raw.effectivePoints === 1 || raw.effectivePoints === 3 || raw.effectivePoints === 5 ? raw.effectivePoints : undefined;
    return { ...common, kind: 'care', status: raw.status, requestedPoints: raw.requestedPoints, effectivePoints, reviewedBy: raw.reviewedBy === 'partner-a' || raw.reviewedBy === 'partner-b' ? raw.reviewedBy : undefined, reviewedAt: typeof raw.reviewedAt === 'string' ? raw.reviewedAt : undefined };
  }
  if (raw.kind === 'feeling') {
    if (raw.status !== 'awaiting_response' && raw.status !== 'responded') throw new Error('感受记录状态无效。');
    if (raw.effectivePoints !== -1 && raw.effectivePoints !== -3 && raw.effectivePoints !== -5) throw new Error('感受扣分无效。');
    return { ...common, kind: 'feeling', status: raw.status, effectivePoints: raw.effectivePoints, response: typeof raw.response === 'string' ? raw.response : undefined, respondedAt: typeof raw.respondedAt === 'string' ? raw.respondedAt : undefined };
  }
  if (raw.kind === 'score_adjustment') {
    if (raw.status !== 'pending' && raw.status !== 'confirmed' && raw.status !== 'declined') throw new Error('调分申请状态无效。');
    if (!Number.isInteger(raw.proposedScore) || (raw.proposedScore as number) < 0 || (raw.proposedScore as number) > 100) throw new Error('调分申请分数无效。');
    return { ...common, kind: 'score_adjustment', status: raw.status, proposedScore: raw.proposedScore as number, confirmedBy: raw.confirmedBy === 'partner-a' || raw.confirmedBy === 'partner-b' ? raw.confirmedBy : undefined };
  }
  if (raw.status !== 'pending' && raw.status !== 'confirmed' && raw.status !== 'declined') throw new Error('共同约定状态无效。');
  const title = text(raw.title, '约定名称');
  const confirmedBy = raw.confirmedBy === 'partner-a' || raw.confirmedBy === 'partner-b' ? raw.confirmedBy : undefined;
  return { ...common, kind: 'rule', title, status: raw.status, confirmedBy };
}

export function parseCloudRecordPage(value: unknown): ParsedRecordPage {
  const raw = object(value, '历史分页');
  if (!Array.isArray(raw.records)) throw new Error('历史记录列表缺失。');
  if (typeof raw.hasMore !== 'boolean' || (raw.nextCursor !== null && typeof raw.nextCursor !== 'string') || (raw.hasMore && !raw.nextCursor)) throw new Error('历史分页信息无效。');
  return { records: raw.records.map(parseRecord), hasMore: raw.hasMore, nextCursor: raw.nextCursor as string | null };
}

export function parseApiEnvelope(value: unknown): unknown {
  const envelope = object(value, '云函数响应');
  if (envelope.ok === false) throw new Error(typeof envelope.message === 'string' ? envelope.message : '云端暂时无法完成此操作。');
  if (envelope.ok !== true || !Object.prototype.hasOwnProperty.call(envelope, 'data')) throw new Error('云函数响应契约无效。');
  return envelope.data;
}

export function parseCloudConnection(value: unknown): ParsedCloudConnection {
  const raw = object(value, '配对状态');
  if (raw.status === 'unpaired') return { status: 'unpaired' };
  if (raw.status === 'deletion_pending') return { status: 'deletion_pending', deleteAfter: text(raw.deleteAfter, '预计删除时间') };
  if (raw.status !== 'paired' || (raw.viewerId !== 'partner-a' && raw.viewerId !== 'partner-b')) throw new Error('配对状态无效。');
  return { status: 'paired', coupleId: text(raw.coupleId, '共同空间 ID'), viewerId: raw.viewerId };
}

export function parsePrivacyExport(value: unknown): ParsedPrivacyExport {
  const raw = object(value, '数据导出');
  const retention = object(raw.retentionPolicy, '数据导出保存期限');
  if (!Number.isInteger(retention.liveDeletionDays) || !Number.isInteger(retention.backupDeletionDays)) throw new Error('数据导出保存期限格式不正确。');
  return {
    exportedAt: text(raw.exportedAt, '数据导出时间'),
    retentionPolicy: { liveDeletionDays: retention.liveDeletionDays as number, backupDeletionDays: retention.backupDeletionDays as number },
    profile: object(raw.profile, '数据导出用户资料'),
    identities: objectArray(raw.identities, '数据导出身份列表'),
    consents: objectArray(raw.consents, '数据导出同意记录'),
    memberships: objectArray(raw.memberships, '数据导出空间成员列表'),
    invites: objectArray(raw.invites, '数据导出邀请列表'),
    authoredRecords: objectArray(raw.authoredRecords, '数据导出本人记录'),
    contributions: objectArray(raw.contributions, '数据导出本人贡献'),
    auditEvents: objectArray(raw.auditEvents, '数据导出审计记录'),
    privacyRequests: objectArray(raw.privacyRequests, '数据导出隐私请求'),
  };
}

export function parseObject(value: unknown, label: string) { return object(value, label); }
export function parseText(value: unknown, label: string) { return text(value, label); }
