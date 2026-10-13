const crypto = require('crypto');
const cloud = require('wx-server-sdk');
const { assertPairingAvailable, responsePatch, careReviewPatch, ruleDecisionPatch, toClientRecord } = require('./lib/contracts');
const { executeMutationInTransaction, withCachedMutationEnvelope } = require('./lib/mutation');
const { buildPersonalRecordExport } = require('./lib/privacy');
const { decodeRecordCursor, encodeRecordCursor, recordCursorWhere, exportCursorWhere, nextExportCursor } = require('./lib/pagination');
const { nextRateLimitState } = require('./lib/rate-limit');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const command = db.command;
const MAX_RECORD_LENGTH = 300;
const IDEMPOTENCY_DAYS = 7;
const LIVE_DELETION_DAYS = 7;
const BACKUP_DELETION_DAYS = 30;
// 清理函数按小时触发，提前一天入队，给调度延迟留出余量，确保不超过对外承诺。
const PRIMARY_DELETE_SCHEDULE_DAYS = LIVE_DELETION_DAYS - 1;
const BACKUP_DELETE_SCHEDULE_DAYS = BACKUP_DELETION_DAYS - 1;
const PRIVACY_NOTICE_VERSION = '2026-08-20-v1';
const SPACE_DELETION_REQUEST_DAYS = 7;
const MAX_EXPORT_ROWS = 1000;
const MAX_EXPORT_RESPONSE_BYTES = 512 * 1024;
const EXPORT_SEGMENT_SIZE = 100;
const MAX_RECORD_ATTACHMENTS = 3;
const MEDIA_TICKET_MINUTES = 15;
const NOTIFICATIONS_ENABLED = process.env.ENABLE_SUBSCRIPTIONS === 'true';
const DEFAULT_MUTATION_RATE = { limit: 60, windowMs: 10 * 60 * 1000 };
const MUTATION_RATE_RULES = {
  care_created: { limit: 30, windowMs: 10 * 60 * 1000 },
  feeling_created: { limit: 30, windowMs: 10 * 60 * 1000 },
  care_reviewed: { limit: 30, windowMs: 10 * 60 * 1000 },
  score_adjustment_proposed: { limit: 10, windowMs: 10 * 60 * 1000 },
  score_adjustment_decided: { limit: 10, windowMs: 10 * 60 * 1000 },
  record_responded: { limit: 30, windowMs: 10 * 60 * 1000 },
  rule_proposed: { limit: 10, windowMs: 10 * 60 * 1000 },
  personal_deletion_requested: { limit: 3, windowMs: 60 * 60 * 1000 },
  space_deletion_requested: { limit: 3, windowMs: 60 * 60 * 1000 },
  notification_subscription_granted: { limit: 6, windowMs: 60 * 60 * 1000 },
};

function success(data) { return { ok: true, data }; }
function fail(message) { return { ok: false, message }; }
function hash(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
function id(prefix) { return `${prefix}_${crypto.randomBytes(18).toString('hex')}`; }
function now() { return new Date().toISOString(); }
function daysFromNow(days) { return new Date(Date.now() + days * 86400000).toISOString(); }
function cleanText(value, field = '内容', max = MAX_RECORD_LENGTH) {
  if (typeof value !== 'string') throw new Error(`${field}不能为空。`);
  const text = value.trim();
  if (text.length < 2) throw new Error(`${field}至少需要两个字。`);
  if (text.length > max) throw new Error(`${field}不能超过${max}字。`);
  return text;
}
function cleanOperationId(value) {
  if (typeof value !== 'string' || !/^op-[a-zA-Z0-9-]{8,100}$/.test(value)) throw new Error('操作凭证无效，请重新打开页面。');
  return value;
}
function cleanScore(value, field = '分数') {
  if (!Number.isInteger(value) || value < 0 || value > 100) throw new Error(`${field}需在0到100之间。`);
  return value;
}
function cleanPositivePoints(value, field = '行动加分') {
  if (value === 1 || value === 3 || value === 5) return value;
  throw new Error(`${field}只能是+1、+3或+5。`);
}
function cleanNegativePoints(value, field = '感受扣分') {
  if (value === -1 || value === -3 || value === -5) return value;
  throw new Error(`${field}只能是-1、-3或-5。`);
}
function cleanTemplateId(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(value)) throw new Error('订阅消息模板编号无效。');
  return value;
}
function cleanAttachments(value) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || value.length > MAX_RECORD_ATTACHMENTS) throw new Error('一次最多上传三张照片。');
  return value.map((item) => {
    if (!item || typeof item.fileId !== 'string' || item.fileId.length < 8 || item.fileId.length > 500) throw new Error('附件文件无效。');
    return { fileId: item.fileId };
  });
}
function cleanAttachmentFileIds(value) {
  return cleanAttachments(Array.isArray(value) ? value.map((fileId) => ({ fileId })) : value).map((item) => item.fileId);
}
function decodePersonalExportCursor(value) {
  if (value === undefined || value === null || value === '') return null;
  if (typeof value !== 'string' || value.length > 500) throw new Error('分段导出游标无效。');
  try {
    const cursor = JSON.parse(Buffer.from(value, 'base64url').toString('utf8'));
    if (!cursor || typeof cursor.snapshotAt !== 'string' || !Number.isInteger(cursor.coupleOffset) || cursor.coupleOffset < 0) throw new Error('invalid');
    if (cursor.recordCursor !== null && (!cursor.recordCursor || typeof cursor.recordCursor.timestamp !== 'string' || typeof cursor.recordCursor._id !== 'string')) throw new Error('invalid');
    return cursor;
  } catch {
    throw new Error('分段导出游标无效。');
  }
}
function encodePersonalExportCursor(cursor) { return Buffer.from(JSON.stringify(cursor), 'utf8').toString('base64url'); }
function changedScore(score, points) { return Math.max(0, Math.min(100, score + points)); }
function scoreFromSettings(settings) { return settings && Number.isInteger(settings.score) ? cleanScore(settings.score) : 70; }
function mutationKey(userId, operationId) { return hash(`${userId}:${operationId}`); }
async function getOrNull(collection, documentId) {
  return collection.doc(documentId).get().catch(() => null);
}
async function addAudit(transaction, coupleId, actorUserId, type, payload = {}) {
  await transaction.collection('audit_events').add({ data: { _id: id('audit'), coupleId: coupleId || null, actorUserId, type, payload, createdAt: now() } });
}
async function partnerMembershipIn(transaction, membership) {
  const result = await transaction.collection('memberships').where({ coupleId: membership.coupleId, status: 'active' }).get();
  const partner = result.data.find((item) => item.userId !== membership.userId);
  if (!partner) throw new Error('共同空间成员状态异常。');
  return partner;
}
async function enqueuePartnerNotification(transaction, membership, actorUserId, type, recordId = null) {
  if (!NOTIFICATIONS_ENABLED) return;
  const partner = await partnerMembershipIn(transaction, membership);
  await transaction.collection('notification_outbox').add({ data: {
    _id: id('notice'), coupleId: membership.coupleId, recipientUserId: partner.userId, actorUserId,
    type, recordId, status: 'pending', createdAt: now(), attempts: 0,
  } });
}
async function recordPrivacyConsent(transaction, userId, version) {
  if (version !== PRIVACY_NOTICE_VERSION) throw new Error('请先阅读并同意最新版隐私说明。');
  const consentId = hash(`${userId}:${version}`);
  const existing = await getOrNull(transaction.collection('privacy_consents'), consentId);
  if (existing && existing.data) return;
  await transaction.collection('privacy_consents').add({ data: { _id: consentId, userId, version, agreedAt: now() } });
}
async function currentPrivacyConsent(userId, collection = db.collection('privacy_consents')) {
  const result = await getOrNull(collection, hash(`${userId}:${PRIVACY_NOTICE_VERSION}`));
  return Boolean(result && result.data);
}
async function requireCurrentPrivacyConsent(userId, collection = db.collection('privacy_consents')) {
  if (!await currentPrivacyConsent(userId, collection)) throw new Error('隐私说明已更新，请阅读并重新同意后继续。');
}
async function assertContentSafe(content) {
  const context = cloud.getWXContext();
  if (!cloud.openapi || !cloud.openapi.security || typeof cloud.openapi.security.msgSecCheck !== 'function') throw new Error('内容安全能力尚未配置，暂时不能保存内容。');
  const result = await cloud.openapi.security.msgSecCheck({ openid: context.OPENID, scene: 2, version: 2, content });
  const suggestion = result && result.result ? result.result.suggest : null;
  if (suggestion !== 'pass') throw new Error('内容未通过微信安全检查，请调整后再提交。');
}
async function enforceRateLimit(transaction, userId, action, rule = MUTATION_RATE_RULES[action] || DEFAULT_MUTATION_RATE) {
  const currentTime = Date.now();
  const bucket = Math.floor(currentTime / rule.windowMs);
  const key = hash(`${userId}:${action}:${bucket}`);
  const existing = await getOrNull(transaction.collection('rate_limits'), key);
  const decision = nextRateLimitState(existing && existing.data ? existing.data : null, currentTime, rule);
  if (!decision.allowed) throw new Error('操作太频繁，请稍后再试。');
  if (existing && existing.data) await transaction.collection('rate_limits').doc(key).update({ data: decision.state });
  else await transaction.collection('rate_limits').add({ data: { _id: key, userId, action, ...decision.state } });
}
async function loadMutationReceipt(userId, operationIdValue, action) {
  const operationId = cleanOperationId(operationIdValue);
  const previous = await getOrNull(db.collection('idempotency_keys'), mutationKey(userId, operationId));
  if (!previous || !previous.data || previous.data.action !== action) return null;
  return { found: true, value: previous.data.result };
}

async function runMutation(userId, operationIdValue, action, worker) {
  const operationId = cleanOperationId(operationIdValue);
  const key = mutationKey(userId, operationId);
  const result = await db.runTransaction((transaction) => executeMutationInTransaction({
    transaction,
    previousResult: async (tx) => {
      const previous = await getOrNull(tx.collection('idempotency_keys'), key);
      if (!previous || !previous.data) return null;
      if (previous.data.action !== action) throw new Error('操作凭证已用于其他操作，请刷新页面后重试。');
      return { found: true, value: previous.data.result };
    },
    beforeWorker: (tx) => enforceRateLimit(tx, userId, action),
    worker,
    addAudit: (tx, outcome) => addAudit(tx, outcome.coupleId, userId, outcome.auditType || action, outcome.auditPayload || {}),
    saveIdempotency: (tx, data) => tx.collection('idempotency_keys').add({ data: { _id: key, userId, operationId, action, result: data, createdAt: now(), expiresAt: daysFromNow(IDEMPOTENCY_DAYS) } }),
  }));
  return success(result);
}

async function runContentMutation(userId, operationId, action, contents, worker) {
  return withCachedMutationEnvelope({
    loadCached: () => loadMutationReceipt(userId, operationId, action),
    execute: async () => {
      // 在把任何亲密关系文本交给内容安全接口前，先拒绝未配对、已删除或
      // 尚未同意最新版说明的调用；事务内仍会再次校验以防止检查后状态变化。
      await requireActiveUser(userId);
      await requireCurrentPrivacyConsent(userId);
      await requireMembership(userId);
      for (const content of contents) await assertContentSafe(content);
      return runMutation(userId, operationId, action, worker);
    },
  });
}

async function ensurePairingLock(userId) {
  const existing = await getOrNull(db.collection('user_pairing_locks'), userId);
  if (existing && existing.data) return;
  await db.collection('user_pairing_locks').add({ data: { _id: userId, userId, activeCoupleId: null, updatedAt: now() } }).catch(async () => {
    const retry = await getOrNull(db.collection('user_pairing_locks'), userId);
    if (!retry || !retry.data) throw new Error('无法初始化配对锁。');
  });
}

async function identity() {
  const context = cloud.getWXContext();
  if (!context.OPENID || !context.APPID) throw new Error('无法确认当前微信身份，请重新打开小程序。');
  const identityId = hash(`${context.APPID}:${context.OPENID}`);
  const existing = await getOrNull(db.collection('user_identities'), identityId);
  if (existing && existing.data) {
    await ensurePairingLock(existing.data.userId);
    return existing.data.userId;
  }

  const userId = id('usr');
  const createdAt = now();
  await db.runTransaction(async (transaction) => {
    const retry = await getOrNull(transaction.collection('user_identities'), identityId);
    if (retry && retry.data) return retry.data.userId;
    await transaction.collection('users').add({ data: { _id: userId, displayName: '', status: 'active', createdAt, updatedAt: createdAt } });
    await transaction.collection('user_identities').add({ data: { _id: identityId, userId, appId: context.APPID, openId: context.OPENID, status: 'active', createdAt } });
    await transaction.collection('user_pairing_locks').add({ data: { _id: userId, userId, activeCoupleId: null, updatedAt: createdAt } });
    return userId;
  });
  const linked = await db.collection('user_identities').doc(identityId).get();
  return linked.data.userId;
}

async function userDocument(userId) {
  const result = await db.collection('users').doc(userId).get();
  return result.data;
}
async function profileFor(userId) {
  const user = await userDocument(userId);
  return { userId, displayName: user.displayName || '未命名的伴侣' };
}
async function membershipFor(userId, collection = db.collection('memberships')) {
  const result = await collection.where({ userId, status: 'active' }).limit(1).get();
  return result.data[0] || null;
}
async function anyMembershipFor(userId) {
  const result = await db.collection('memberships').where({ userId }).orderBy('createdAt', 'desc').limit(1).get();
  return result.data[0] || null;
}
async function requireMembership(userId) {
  const membership = await membershipFor(userId);
  if (!membership) throw new Error('请先与伴侣完成共同空间配对。');
  const couple = await db.collection('couples').doc(membership.coupleId).get();
  if (!couple.data || couple.data.status !== 'active') throw new Error('这个共同空间已经关闭。');
  return membership;
}
async function requireMembershipIn(transaction, userId) {
  const membership = await membershipFor(userId, transaction.collection('memberships'));
  if (!membership) throw new Error('请先与伴侣完成共同空间配对。');
  const couple = await transaction.collection('couples').doc(membership.coupleId).get();
  if (!couple.data || couple.data.status !== 'active') throw new Error('这个共同空间已经关闭。');
  return { membership, couple: couple.data };
}
async function requireActiveUser(userId) {
  const user = await userDocument(userId);
  if (user.status !== 'active') throw new Error('该账号正在执行数据删除，不能继续写入。');
}

async function bootstrap(userId) {
  const user = await userDocument(userId);
  const profile = { userId, displayName: user.displayName || '未命名的伴侣' };
  const privacyNotice = { version: PRIVACY_NOTICE_VERSION, required: !await currentPrivacyConsent(userId) };
  if (user.status === 'deletion_pending') return success({ profile, privacyNotice, connection: { status: 'deletion_pending', deleteAfter: user.deleteAfter } });
  const membership = await membershipFor(userId);
  if (!membership) return success({ profile, privacyNotice, connection: { status: 'unpaired' } });
  return success({ profile, privacyNotice, connection: { status: 'paired', coupleId: membership.coupleId, viewerId: membership.partnerId } });
}

async function acceptPrivacyNotice(userId, version, operationId) {
  await requireActiveUser(userId);
  return runMutation(userId, operationId, 'privacy_notice_accepted', async (transaction) => {
    await recordPrivacyConsent(transaction, userId, version);
    return { data: { version: PRIVACY_NOTICE_VERSION, required: false }, auditType: 'privacy_notice_accepted', auditPayload: { version } };
  });
}

async function updateProfile(userId, displayName, operationId) {
  return withCachedMutationEnvelope({
    loadCached: () => loadMutationReceipt(userId, operationId, 'profile_updated'),
    execute: async () => {
      const name = cleanText(displayName, '称呼', 20);
      await requireActiveUser(userId);
      await requireCurrentPrivacyConsent(userId);
      await assertContentSafe(name);
      return runMutation(userId, operationId, 'profile_updated', async (transaction) => {
        await transaction.collection('users').doc(userId).update({ data: { displayName: name, updatedAt: now() } });
        return { data: { userId, displayName: name }, auditType: 'profile_updated' };
      });
    },
  });
}

async function createInvite(userId, displayName, initialScoreValue, operationId) {
  return withCachedMutationEnvelope({
    loadCached: () => loadMutationReceipt(userId, operationId, 'pair_invite_created'),
    execute: async () => {
      const name = cleanText(displayName, '称呼', 20);
      const initialScore = cleanScore(initialScoreValue, '初始分数');
      await requireActiveUser(userId);
      await requireCurrentPrivacyConsent(userId);
      await assertContentSafe(name);
      await ensurePairingLock(userId);
      const inviteCode = `${crypto.randomBytes(6).toString('base64url')}.${crypto.randomBytes(12).toString('base64url')}`;
      const createdAt = now();
      const expiresAt = daysFromNow(1);
      return runMutation(userId, operationId, 'pair_invite_created', async (transaction) => {
        const lock = await transaction.collection('user_pairing_locks').doc(userId).get();
        if (lock.data.activeCoupleId) throw new Error('你已经在一个共同空间中，不能再创建新的邀请。');
        const membership = await membershipFor(userId, transaction.collection('memberships'));
        if (membership) throw new Error('你已经在一个共同空间中，不能再创建新的邀请。');
        await transaction.collection('users').doc(userId).update({ data: { displayName: name, updatedAt: createdAt } });
        await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
        await transaction.collection('pair_invites').where({ creatorUserId: userId, status: 'active' }).update({ data: { status: 'cancelled', cancelledAt: createdAt } });
        await transaction.collection('pair_invites').add({ data: { _id: id('invite'), codeHash: hash(inviteCode), creatorUserId: userId, initialScore, status: 'active', createdAt, expiresAt } });
        return { data: { inviteCode, expiresAt, initialScore }, auditType: 'pair_invite_created', auditPayload: { expiresAt, initialScore } };
      });
    },
  });
}

async function cancelInvite(userId, operationId) {
  return runMutation(userId, operationId, 'pair_invite_cancelled', async (transaction) => {
    const result = await transaction.collection('pair_invites').where({ creatorUserId: userId, status: 'active' }).update({ data: { status: 'cancelled', cancelledAt: now() } });
    return { data: { cancelled: result.stats ? result.stats.updated : 0 }, auditType: 'pair_invite_cancelled' };
  });
}

async function previewInvite(userId, inviteCode) {
  await requireActiveUser(userId);
  const codeHash = hash(cleanText(inviteCode, '邀请码', 200));
  const found = await db.collection('pair_invites').where({ codeHash }).limit(1).get();
  const invite = found.data[0];
  if (!invite || invite.status !== 'active' || Date.parse(invite.expiresAt) <= Date.now()) throw new Error('邀请码已失效，请让对方重新创建。');
  return success({ initialScore: cleanScore(invite.initialScore, '邀请初始分数') });
}

async function generateInviteMiniCode(userId, inviteCodeValue) {
  const inviteCode = cleanText(inviteCodeValue, '邀请码', 200);
  await requireActiveUser(userId);
  await requireCurrentPrivacyConsent(userId);
  const result = await db.collection('pair_invites').where({ codeHash: hash(inviteCode), creatorUserId: userId, status: 'active' }).limit(1).get();
  const invite = result.data[0];
  if (!invite || Date.parse(invite.expiresAt) <= Date.now()) throw new Error('邀请码已失效，请重新创建。');
  if (!cloud.openapi || !cloud.openapi.wxacode || typeof cloud.openapi.wxacode.getUnlimited !== 'function') throw new Error('小程序码能力尚未配置。');
  const code = await cloud.openapi.wxacode.getUnlimited({
    scene: `i=${inviteCode}`,
    page: 'pages/pair/index',
    checkPath: false,
    envVersion: process.env.MINIPROGRAM_ENV_VERSION || 'trial',
    width: 430,
  });
  const uploaded = await cloud.uploadFile({ cloudPath: `invite-codes/${hash(inviteCode)}.png`, fileContent: code.buffer });
  await db.collection('pair_invites').doc(invite._id).update({ data: { miniCodeFileId: uploaded.fileID, miniCodeGeneratedAt: now() } });
  return success({ fileId: uploaded.fileID, expiresAt: invite.expiresAt });
}

async function prepareMediaUpload(userId, operationId) {
  if (process.env.ENABLE_MEDIA_UPLOADS !== 'true') throw new Error('照片上传尚未在当前环境启用。');
  return runMutation(userId, operationId, 'media_upload_prepared', async (transaction) => {
    await requireActiveUser(userId);
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const ticketId = id('media');
    const cloudPathPrefix = `relationship-media/${membership.coupleId}/${ticketId}`;
    await transaction.collection('media_upload_tickets').add({ data: { _id: ticketId, coupleId: membership.coupleId, userId, cloudPathPrefix, status: 'active', createdAt: now(), expiresAt: new Date(Date.now() + MEDIA_TICKET_MINUTES * 60 * 1000).toISOString() } });
    return { data: { ticketId, cloudPathPrefix }, coupleId: membership.coupleId, auditType: 'media_upload_prepared' };
  });
}

async function registerMediaUploadFiles(userId, ticketIdValue, fileIdsValue, operationId) {
  const ticketId = cleanText(ticketIdValue, '附件上传凭证', 100);
  const fileIds = cleanAttachmentFileIds(fileIdsValue);
  if (fileIds.length === 0) throw new Error('请至少上传一张照片。');
  return runMutation(userId, operationId, 'media_upload_registered', async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const ticket = await transaction.collection('media_upload_tickets').doc(ticketId).get();
    if (!ticket.data || ticket.data.status !== 'active' || ticket.data.userId !== userId || ticket.data.coupleId !== membership.coupleId || Date.parse(ticket.data.expiresAt) <= Date.now() || fileIds.some((fileId) => !fileId.includes(ticket.data.cloudPathPrefix))) throw new Error('附件上传凭证无效或已失效。');
    await transaction.collection('media_upload_tickets').doc(ticketId).update({ data: { fileIds, registeredAt: now() } });
    return { data: { registered: fileIds.length }, coupleId: membership.coupleId, auditType: 'media_upload_registered' };
  });
}

async function acceptInvite(userId, inviteCode, displayName, initialScoreValue, operationId) {
  return withCachedMutationEnvelope({
    loadCached: () => loadMutationReceipt(userId, operationId, 'pair_invite_accepted'),
    execute: async () => {
      const name = cleanText(displayName, '称呼', 20);
      const initialScore = cleanScore(initialScoreValue, '共同初始分数');
      await requireActiveUser(userId);
      await requireCurrentPrivacyConsent(userId);
      await assertContentSafe(name);
      const codeHash = hash(cleanText(inviteCode, '邀请码', 200));
      const found = await db.collection('pair_invites').where({ codeHash }).limit(1).get();
      const invite = found.data[0];
      if (!invite) throw new Error('邀请码已失效，请让对方重新创建。');
      if (invite.status === 'accepted' && invite.acceptedBy === userId) {
        return withCachedMutationEnvelope({
          loadCached: () => loadMutationReceipt(userId, operationId, 'pair_invite_accepted'),
          execute: async () => { throw new Error('配对已成功，正在恢复结果，请稍后重试。'); },
        });
      }
      if (invite.status !== 'active') throw new Error('邀请码已失效，请让对方重新创建。');
      await ensurePairingLock(userId);
      await ensurePairingLock(invite.creatorUserId);
      const coupleId = id('couple');
      const createdAt = now();
      return runMutation(userId, operationId, 'pair_invite_accepted', async (transaction) => {
        const freshInvite = await transaction.collection('pair_invites').doc(invite._id).get();
        const creatorLock = await transaction.collection('user_pairing_locks').doc(invite.creatorUserId).get();
        const accepterLock = await transaction.collection('user_pairing_locks').doc(userId).get();
        const creatorMembership = await membershipFor(invite.creatorUserId, transaction.collection('memberships'));
        const accepterMembership = await membershipFor(userId, transaction.collection('memberships'));
        if (creatorMembership) creatorLock.data.activeCoupleId = creatorMembership.coupleId;
        if (accepterMembership) accepterLock.data.activeCoupleId = accepterMembership.coupleId;
        assertPairingAvailable({ invite: freshInvite.data, creatorLock: creatorLock.data, accepterLock: accepterLock.data, currentTime: Date.now() });

        await transaction.collection('users').doc(userId).update({ data: { displayName: name, updatedAt: createdAt } });
        await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
        await transaction.collection('couples').add({ data: { _id: coupleId, status: 'active', createdAt, memberIds: [invite.creatorUserId, userId] } });
        await transaction.collection('memberships').add({ data: { _id: id('member'), coupleId, userId: invite.creatorUserId, partnerId: 'partner-a', status: 'active', createdAt } });
        await transaction.collection('memberships').add({ data: { _id: id('member'), coupleId, userId, partnerId: 'partner-b', status: 'active', createdAt } });
        await transaction.collection('couple_settings').add({ data: { _id: coupleId, score: initialScore, initializedBy: userId, initializedAt: createdAt, updatedAt: createdAt } });
        await transaction.collection('pair_invites').doc(invite._id).update({ data: { status: 'accepted', acceptedBy: userId, acceptedAt: createdAt } });
        await transaction.collection('user_pairing_locks').doc(invite.creatorUserId).update({ data: { activeCoupleId: coupleId, updatedAt: createdAt } });
        await transaction.collection('user_pairing_locks').doc(userId).update({ data: { activeCoupleId: coupleId, updatedAt: createdAt } });
        return { data: { status: 'paired', coupleId, viewerId: 'partner-b' }, coupleId, auditType: 'pair_invite_accepted', auditPayload: { initialScore, inviterSuggestedScore: invite.initialScore } };
      });
    },
  });
}

async function createRecord(userId, kind, content, pointsValue, operationId, uploadTicketIdValue, attachmentsValue) {
  if (kind !== 'care' && kind !== 'feeling') throw new Error('不支持的记录类型。');
  const normalized = cleanText(content);
  const points = kind === 'care' ? cleanPositivePoints(pointsValue) : cleanNegativePoints(pointsValue);
  const attachments = cleanAttachments(attachmentsValue);
  const uploadTicketId = attachments.length > 0 ? cleanText(uploadTicketIdValue, '附件上传凭证', 100) : null;
  const recordId = `record_${hash(`${userId}:${operationId}`).slice(0, 36)}`;
  return runContentMutation(userId, operationId, `${kind}_created`, [normalized], async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    if (attachments.length > 0) {
      const ticket = await transaction.collection('media_upload_tickets').doc(uploadTicketId).get();
      if (!ticket.data || ticket.data.status !== 'active' || ticket.data.userId !== userId || ticket.data.coupleId !== membership.coupleId || Date.parse(ticket.data.expiresAt) <= Date.now() || !Array.isArray(ticket.data.fileIds) || ticket.data.fileIds.length !== attachments.length || attachments.some((item) => !ticket.data.fileIds.includes(item.fileId))) throw new Error('附件上传凭证无效或已失效。');
      await transaction.collection('media_upload_tickets').doc(uploadTicketId).update({ data: { status: 'consumed', consumedAt: now() } });
    }
    const record = {
      _id: recordId, coupleId: membership.coupleId, kind, authorId: membership.partnerId, content: normalized, createdAt: now(),
      ...(attachments.length > 0 ? { attachments } : {}),
      ...(kind === 'care' ? { status: 'pending', requestedPoints: points } : { status: 'awaiting_response', effectivePoints: points }),
    };
    await transaction.collection('relationship_records').add({ data: record });
    await enqueuePartnerNotification(transaction, membership, userId, kind === 'care' ? 'care_pending' : 'feeling_pending', recordId);
    if (kind === 'feeling') {
      const settings = await transaction.collection('couple_settings').doc(membership.coupleId).get();
      const score = changedScore(scoreFromSettings(settings.data), points);
      await transaction.collection('couple_settings').doc(membership.coupleId).update({ data: { score, updatedAt: now() } });
      return { data: toClientRecord(record), coupleId: membership.coupleId, auditType: 'feeling_deducted', auditPayload: { recordId, points, score } };
    }
    return { data: toClientRecord(record), coupleId: membership.coupleId, auditType: 'care_created', auditPayload: { recordId, requestedPoints: points } };
  });
}

async function reviewCare(userId, recordIdValue, decision, effectivePointsValue, operationId) {
  const recordId = cleanText(recordIdValue, '行动编号', 100);
  const effectivePoints = decision === 'approved' ? cleanPositivePoints(effectivePointsValue, '实际加分') : null;
  return runMutation(userId, operationId, 'care_reviewed', async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const record = await transaction.collection('relationship_records').doc(recordId).get();
    if (record.data.coupleId !== membership.coupleId) throw new Error('你不能审批这条行动。');
    const reviewedAt = now();
    const patch = careReviewPatch(record.data, membership.partnerId, decision, effectivePoints, reviewedAt);
    await transaction.collection('relationship_records').doc(recordId).update({ data: patch });
    await enqueuePartnerNotification(transaction, membership, userId, decision === 'approved' ? 'care_approved' : 'care_rejected', recordId);
    let score = null;
    if (decision === 'approved') {
      const settings = await transaction.collection('couple_settings').doc(membership.coupleId).get();
      score = changedScore(scoreFromSettings(settings.data), effectivePoints);
      await transaction.collection('couple_settings').doc(membership.coupleId).update({ data: { score, updatedAt: reviewedAt } });
    }
    return { data: null, coupleId: membership.coupleId, auditType: decision === 'approved' ? 'care_approved' : 'care_rejected', auditPayload: { recordId, effectivePoints, score } };
  });
}

async function respondToRecord(userId, recordIdValue, response, operationId) {
  const recordId = cleanText(recordIdValue, '记录编号', 100);
  const normalized = cleanText(response, '回应');
  return runContentMutation(userId, operationId, 'record_responded', [normalized], async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const record = await transaction.collection('relationship_records').doc(recordId).get();
    if (record.data.coupleId !== membership.coupleId) throw new Error('你不能回应这条记录。');
    const patch = responsePatch(record.data, membership.partnerId, normalized, now());
    await transaction.collection('relationship_records').doc(recordId).update({ data: patch });
    await enqueuePartnerNotification(transaction, membership, userId, 'feeling_responded', recordId);
    return { data: null, coupleId: membership.coupleId, auditType: 'record_responded', auditPayload: { recordId } };
  });
}

async function proposeRule(userId, title, content, operationId) {
  const normalizedTitle = cleanText(title, '约定名称', 50);
  const normalizedContent = cleanText(content);
  const recordId = `record_${hash(`${userId}:${operationId}`).slice(0, 36)}`;
  return runContentMutation(userId, operationId, 'rule_proposed', [normalizedTitle, normalizedContent], async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const record = { _id: recordId, coupleId: membership.coupleId, kind: 'rule', authorId: membership.partnerId, title: normalizedTitle, content: normalizedContent, createdAt: now(), status: 'pending' };
    await transaction.collection('relationship_records').add({ data: record });
    await enqueuePartnerNotification(transaction, membership, userId, 'rule_pending', recordId);
    return { data: toClientRecord(record), coupleId: membership.coupleId, auditType: 'rule_proposed', auditPayload: { recordId } };
  });
}

async function decideRule(userId, recordIdValue, accept, operationId) {
  const recordId = cleanText(recordIdValue, '约定编号', 100);
  return runMutation(userId, operationId, accept ? 'rule_confirmed' : 'rule_declined', async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const record = await transaction.collection('relationship_records').doc(recordId).get();
    if (record.data.coupleId !== membership.coupleId) throw new Error('这条约定暂时无法由你处理。');
    const decidedAt = now();
    const patch = ruleDecisionPatch(record.data, membership.partnerId, accept, decidedAt);
    await transaction.collection('relationship_records').doc(recordId).update({ data: patch });
    await enqueuePartnerNotification(transaction, membership, userId, accept ? 'rule_confirmed' : 'rule_declined', recordId);
    return { data: null, coupleId: membership.coupleId, auditType: accept ? 'rule_confirmed' : 'rule_declined', auditPayload: { recordId } };
  });
}

async function proposeScoreAdjustment(userId, scoreValue, reason, operationId) {
  const proposedScore = cleanScore(scoreValue, '建议分数');
  const normalizedReason = cleanText(reason, '调分说明');
  const recordId = `record_${hash(`${userId}:${operationId}`).slice(0, 36)}`;
  return runContentMutation(userId, operationId, 'score_adjustment_proposed', [normalizedReason], async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const record = { _id: recordId, coupleId: membership.coupleId, kind: 'score_adjustment', authorId: membership.partnerId, content: normalizedReason, proposedScore, createdAt: now(), status: 'pending' };
    await transaction.collection('relationship_records').add({ data: record });
    await enqueuePartnerNotification(transaction, membership, userId, 'score_adjustment_pending', recordId);
    return { data: toClientRecord(record), coupleId: membership.coupleId, auditType: 'score_adjustment_proposed', auditPayload: { recordId, proposedScore } };
  });
}

async function decideScoreAdjustment(userId, recordIdValue, accept, operationId) {
  const recordId = cleanText(recordIdValue, '调分申请编号', 100);
  return runMutation(userId, operationId, 'score_adjustment_decided', async (transaction) => {
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    const { membership } = await requireMembershipIn(transaction, userId);
    const record = await transaction.collection('relationship_records').doc(recordId).get();
    if (record.data.coupleId !== membership.coupleId || record.data.kind !== 'score_adjustment') throw new Error('这条调分申请暂时无法由你处理。');
    const patch = ruleDecisionPatch(record.data, membership.partnerId, accept, now());
    await transaction.collection('relationship_records').doc(recordId).update({ data: patch });
    await enqueuePartnerNotification(transaction, membership, userId, accept ? 'score_adjustment_confirmed' : 'score_adjustment_declined', recordId);
    if (accept) await transaction.collection('couple_settings').doc(membership.coupleId).update({ data: { score: cleanScore(record.data.proposedScore, '建议分数'), updatedAt: now() } });
    return { data: null, coupleId: membership.coupleId, auditType: accept ? 'score_adjustment_confirmed' : 'score_adjustment_declined', auditPayload: { recordId, proposedScore: record.data.proposedScore } };
  });
}

async function listRecords(userId, rawCursor) {
  await requireCurrentPrivacyConsent(userId);
  const membership = await requireMembership(userId);
  const cursor = decodeRecordCursor(rawCursor);
  const pageSize = 100;
  const result = await db.collection('relationship_records')
    .where(recordCursorWhere(command, membership.coupleId, cursor))
    .orderBy('createdAt', 'desc')
    .orderBy('_id', 'desc')
    .limit(pageSize)
    .get();
  const last = result.data[result.data.length - 1];
  return success({ records: result.data.map(toClientRecord), hasMore: result.data.length === pageSize, nextCursor: result.data.length === pageSize ? encodeRecordCursor(last) : null });
}

async function getSettings(userId) {
  await requireCurrentPrivacyConsent(userId);
  const membership = await requireMembership(userId);
  const result = await db.collection('couple_settings').doc(membership.coupleId).get();
  return success({ score: scoreFromSettings(result.data) });
}

async function recordSubscriptionGrant(userId, templateIdValue, operationId) {
  if (!NOTIFICATIONS_ENABLED) throw new Error('关系动态提醒尚未在当前环境启用。');
  const templateId = cleanTemplateId(templateIdValue);
  return runMutation(userId, operationId, 'notification_subscription_granted', async (transaction) => {
    await requireActiveUser(userId);
    await requireCurrentPrivacyConsent(userId, transaction.collection('privacy_consents'));
    await transaction.collection('subscription_grants').add({ data: {
      _id: id('subscription'), userId, templateId, remainingQuota: 1, acceptedAt: now(),
    } });
    return { data: { enabled: true }, auditType: 'notification_subscription_granted', auditPayload: { templateId } };
  });
}

async function closeCoupleIn(transaction, couple, actorUserId, reason) {
  const closedAt = now();
  await transaction.collection('couples').doc(couple._id).update({ data: { status: 'closed', closedAt, closedBy: actorUserId, closeReason: reason } });
  await transaction.collection('memberships').where({ coupleId: couple._id, status: 'active' }).update({ data: { status: 'revoked', revokedAt: closedAt } });
  for (const memberId of couple.memberIds || []) {
    await transaction.collection('user_pairing_locks').doc(memberId).update({ data: { activeCoupleId: null, updatedAt: closedAt } });
  }
  await transaction.collection('privacy_requests').where({ coupleId: couple._id, status: 'pending_partner_confirmation' }).update({ data: {
    status: 'cancelled_space_closed',
    cancelledAt: closedAt,
    requestedBy: command.remove(),
    requestedByPartnerId: command.remove(),
    confirmedBy: command.remove(),
  } });
}

async function leaveSpace(userId, operationId) {
  return runMutation(userId, operationId, 'couple_closed_unilaterally', async (transaction) => {
    const { membership, couple } = await requireMembershipIn(transaction, userId);
    await closeCoupleIn(transaction, couple, userId, 'unilateral_exit');
    return { data: null, coupleId: membership.coupleId, auditType: 'couple_closed_unilaterally' };
  });
}

async function readAllAtSnapshot(collectionName, query, timestampField, snapshotAt) {
  const result = [];
  let cursor = null;
  while (true) {
    const page = await db.collection(collectionName)
      .where(exportCursorWhere(command, query, timestampField, snapshotAt, cursor))
      .orderBy(timestampField, 'desc')
      .orderBy('_id', 'desc')
      .limit(100)
      .get();
    result.push(...page.data);
    if (result.length > MAX_EXPORT_ROWS) throw new Error('可导出的数据量较大，当前版本不能安全地一次复制。请联系运营方获取分段导出。');
    if (page.data.length < 100) return result;
    cursor = nextExportCursor(page.data[page.data.length - 1], timestampField);
  }
}

function assertExportResponseSize(data) {
  if (Buffer.byteLength(JSON.stringify(data), 'utf8') > MAX_EXPORT_RESPONSE_BYTES) throw new Error('可导出的数据量较大，当前版本不能安全地一次复制。请联系运营方获取分段导出。');
  return data;
}

async function exportMyData(userId) {
  await db.runTransaction(async (transaction) => {
    await enforceRateLimit(transaction, userId, 'personal_data_exported', { limit: 3, windowMs: 60 * 60 * 1000 });
    await addAudit(transaction, null, userId, 'personal_data_exported');
  });
  const snapshotAt = now();
  const [profile, identities, consents, memberships, invites, personalPrivacyRequests, spacePrivacyRequests, ownAudits] = await Promise.all([
    userDocument(userId),
    readAllAtSnapshot('user_identities', { userId }, 'createdAt', snapshotAt),
    readAllAtSnapshot('privacy_consents', { userId }, 'agreedAt', snapshotAt),
    readAllAtSnapshot('memberships', { userId }, 'createdAt', snapshotAt),
    readAllAtSnapshot('pair_invites', { creatorUserId: userId }, 'createdAt', snapshotAt),
    readAllAtSnapshot('privacy_requests', { userId }, 'createdAt', snapshotAt),
    readAllAtSnapshot('privacy_requests', { requestedBy: userId }, 'createdAt', snapshotAt),
    readAllAtSnapshot('audit_events', { actorUserId: userId }, 'createdAt', snapshotAt),
  ]);
  const privacyRequests = [...new Map([...personalPrivacyRequests, ...spacePrivacyRequests].map((item) => [item._id, item])).values()];
  const coupleIds = [...new Set(memberships.map((membership) => membership.coupleId))];
  const records = (await Promise.all(coupleIds.map((coupleId) => readAllAtSnapshot('relationship_records', { coupleId }, 'createdAt', snapshotAt)))).flat();
  const personalRecords = buildPersonalRecordExport(records, memberships);
  return success(assertExportResponseSize({
    exportedAt: now(),
    snapshotAt,
    retentionPolicy: { liveDeletionDays: LIVE_DELETION_DAYS, backupDeletionDays: BACKUP_DELETION_DAYS },
    profile,
    identities: identities.map(({ openId, ...item }) => ({ ...item, openIdHash: hash(openId) })),
    consents,
    memberships,
    invites: invites.map(({ codeHash, acceptedBy, ...item }) => item),
    authoredRecords: personalRecords.authoredRecords,
    contributions: personalRecords.contributions,
    auditEvents: ownAudits,
    privacyRequests: privacyRequests.map(({ confirmedBy, ...item }) => item),
  }));
}

async function exportMyDataSegment(userId, rawCursor) {
  await db.runTransaction(async (transaction) => {
    await enforceRateLimit(transaction, userId, 'personal_data_segment_exported', { limit: 30, windowMs: 60 * 60 * 1000 });
    await addAudit(transaction, null, userId, 'personal_data_segment_exported');
  });
  const cursor = decodePersonalExportCursor(rawCursor);
  const snapshotAt = cursor ? cursor.snapshotAt : now();
  const memberships = await readAllAtSnapshot('memberships', { userId }, 'createdAt', snapshotAt);
  const coupleIds = [...new Set(memberships.map((membership) => membership.coupleId).filter(Boolean))];
  let coupleOffset = cursor ? cursor.coupleOffset : 0;
  let recordCursor = cursor ? cursor.recordCursor : null;
  while (coupleOffset < coupleIds.length) {
    const coupleId = coupleIds[coupleOffset];
    const member = memberships.find((item) => item.coupleId === coupleId);
    const page = await db.collection('relationship_records')
      .where(exportCursorWhere(command, { coupleId }, 'createdAt', snapshotAt, recordCursor))
      .orderBy('createdAt', 'desc')
      .orderBy('_id', 'desc')
      .limit(EXPORT_SEGMENT_SIZE)
      .get();
    const personal = buildPersonalRecordExport(page.data, [member]);
    if (page.data.length === EXPORT_SEGMENT_SIZE) {
      return success({
        exportedAt: now(), snapshotAt, segment: { authoredRecords: personal.authoredRecords, contributions: personal.contributions },
        nextCursor: encodePersonalExportCursor({ snapshotAt, coupleOffset, recordCursor: nextExportCursor(page.data[page.data.length - 1], 'createdAt') }),
      });
    }
    if (personal.authoredRecords.length || personal.contributions.length || coupleOffset === coupleIds.length - 1) {
      return success({
        exportedAt: now(), snapshotAt, segment: { authoredRecords: personal.authoredRecords, contributions: personal.contributions },
        nextCursor: coupleOffset + 1 < coupleIds.length ? encodePersonalExportCursor({ snapshotAt, coupleOffset: coupleOffset + 1, recordCursor: null }) : null,
      });
    }
    coupleOffset += 1;
    recordCursor = null;
  }
  return success({ exportedAt: now(), snapshotAt, segment: { authoredRecords: [], contributions: [] }, nextCursor: null });
}

async function requestPersonalDeletion(userId, operationId) {
  const deleteAfter = daysFromNow(PRIMARY_DELETE_SCHEDULE_DAYS);
  const requestId = id('privacy');
  return runMutation(userId, operationId, 'personal_deletion_requested', async (transaction) => {
    const user = await transaction.collection('users').doc(userId).get();
    if (user.data.status === 'deletion_pending') return { data: { requestId: user.data.deletionRequestId, deleteAfter: user.data.deleteAfter }, auditType: 'personal_deletion_request_reused' };
    const membership = await membershipFor(userId, transaction.collection('memberships'));
    let couple = null;
    if (membership) {
      const result = await transaction.collection('couples').doc(membership.coupleId).get();
      couple = result.data;
      if (couple.status === 'active') await closeCoupleIn(transaction, couple, userId, 'personal_deletion');
    }
    await transaction.collection('users').doc(userId).update({ data: { status: 'deletion_pending', deletionRequestId: requestId, deleteAfter, updatedAt: now() } });
    await transaction.collection('privacy_requests').add({ data: { _id: requestId, type: 'personal_deletion', userId, coupleId: membership ? membership.coupleId : null, status: 'scheduled', createdAt: now(), executeAfter: deleteAfter, backupDeleteAfter: daysFromNow(BACKUP_DELETE_SCHEDULE_DAYS) } });
    return { data: { requestId, deleteAfter }, coupleId: membership ? membership.coupleId : null, auditType: 'personal_deletion_requested', auditPayload: { requestId, deleteAfter } };
  });
}

async function requestSpaceDeletion(userId, operationId) {
  const requestId = id('privacy');
  const expiresAt = daysFromNow(SPACE_DELETION_REQUEST_DAYS);
  return runMutation(userId, operationId, 'space_deletion_requested', async (transaction) => {
    const { membership } = await requireMembershipIn(transaction, userId);
    const existing = await transaction.collection('privacy_requests').where({ coupleId: membership.coupleId, type: 'space_deletion', status: 'pending_partner_confirmation' }).limit(1).get();
    if (existing.data[0] && Date.parse(existing.data[0].expiresAt) > Date.now()) return { data: { requestId: existing.data[0]._id, expiresAt: existing.data[0].expiresAt }, coupleId: membership.coupleId, auditType: 'space_deletion_request_reused' };
    if (existing.data[0]) await transaction.collection('privacy_requests').doc(existing.data[0]._id).update({ data: { status: 'cancelled_expired', cancelledAt: now(), requestedBy: command.remove(), requestedByPartnerId: command.remove(), confirmedBy: command.remove() } });
    await transaction.collection('privacy_requests').add({ data: { _id: requestId, type: 'space_deletion', coupleId: membership.coupleId, requestedBy: userId, requestedByPartnerId: membership.partnerId, status: 'pending_partner_confirmation', createdAt: now(), expiresAt } });
    return { data: { requestId, expiresAt }, coupleId: membership.coupleId, auditType: 'space_deletion_requested', auditPayload: { requestId, expiresAt } };
  });
}

async function privacyStatus(userId) {
  const membership = await membershipFor(userId);
  if (!membership) return success({ requests: [] });
  const requests = await db.collection('privacy_requests').where({ coupleId: membership.coupleId, status: 'pending_partner_confirmation' }).get();
  return success({ requests: requests.data.filter((item) => item.requestedBy !== userId && Date.parse(item.expiresAt) > Date.now()).map((item) => ({ id: item._id, type: item.type, createdAt: item.createdAt, expiresAt: item.expiresAt })) });
}

async function confirmSpaceDeletion(userId, requestIdValue, operationId) {
  const requestId = cleanText(requestIdValue, '删除请求编号', 100);
  const executeAfter = daysFromNow(PRIMARY_DELETE_SCHEDULE_DAYS);
  return runMutation(userId, operationId, 'space_deletion_confirmed', async (transaction) => {
    const { membership, couple } = await requireMembershipIn(transaction, userId);
    const request = await transaction.collection('privacy_requests').doc(requestId).get();
    if (request.data.type !== 'space_deletion' || request.data.status !== 'pending_partner_confirmation' || Date.parse(request.data.expiresAt) <= Date.now() || request.data.coupleId !== membership.coupleId || request.data.requestedBy === userId) throw new Error('这条共同空间删除请求无法由你确认。');
    await transaction.collection('privacy_requests').doc(requestId).update({ data: { status: 'scheduled', confirmedBy: userId, confirmedAt: now(), executeAfter, backupDeleteAfter: daysFromNow(BACKUP_DELETE_SCHEDULE_DAYS) } });
    await closeCoupleIn(transaction, couple, userId, 'space_deletion_confirmed');
    return { data: { requestId, executeAfter }, coupleId: membership.coupleId, auditType: 'space_deletion_confirmed', auditPayload: { requestId, executeAfter } };
  });
}

exports.main = async (event) => {
  try {
    const userId = await identity();
    switch (event.action) {
      case 'bootstrap': return await bootstrap(userId);
      case 'acceptPrivacyNotice': return await acceptPrivacyNotice(userId, event.version, event.operationId);
      case 'updateProfile': return await updateProfile(userId, event.displayName, event.operationId);
      case 'createInvite': return await createInvite(userId, event.displayName, event.initialScore, event.operationId);
      case 'cancelInvite': return await cancelInvite(userId, event.operationId);
      case 'previewInvite': return await previewInvite(userId, event.inviteCode);
      case 'generateInviteMiniCode': return await generateInviteMiniCode(userId, event.inviteCode);
      case 'prepareMediaUpload': return await prepareMediaUpload(userId, event.operationId);
      case 'registerMediaUploadFiles': return await registerMediaUploadFiles(userId, event.ticketId, event.fileIds, event.operationId);
      case 'acceptInvite': return await acceptInvite(userId, event.inviteCode, event.displayName, event.initialScore, event.operationId);
      case 'createRecord': return await createRecord(userId, event.kind, event.content, event.points, event.operationId, event.uploadTicketId, event.attachments);
      case 'respondToRecord': return await respondToRecord(userId, event.recordId, event.response, event.operationId);
      case 'reviewCare': return await reviewCare(userId, event.recordId, event.decision, event.effectivePoints, event.operationId);
      case 'proposeRule': return await proposeRule(userId, event.title, event.content, event.operationId);
      case 'decideRule': return await decideRule(userId, event.recordId, event.accept === true, event.operationId);
      case 'proposeScoreAdjustment': return await proposeScoreAdjustment(userId, event.score, event.reason, event.operationId);
      case 'decideScoreAdjustment': return await decideScoreAdjustment(userId, event.recordId, event.accept === true, event.operationId);
      case 'listRecords': return await listRecords(userId, event.cursor);
      case 'getSettings': return await getSettings(userId);
      case 'recordSubscriptionGrant': return await recordSubscriptionGrant(userId, event.templateId, event.operationId);
      case 'leaveSpace': return await leaveSpace(userId, event.operationId);
      case 'exportMyData': return await exportMyData(userId);
      case 'exportMyDataSegment': return await exportMyDataSegment(userId, event.cursor);
      case 'requestPersonalDeletion': return await requestPersonalDeletion(userId, event.operationId);
      case 'requestSpaceDeletion': return await requestSpaceDeletion(userId, event.operationId);
      case 'getPrivacyStatus': return await privacyStatus(userId);
      case 'confirmSpaceDeletion': return await confirmSpaceDeletion(userId, event.requestId, event.operationId);
      default: return fail('不支持的操作。');
    }
  } catch (error) {
    console.error('[relationship-api]', error);
    return fail(error instanceof Error ? error.message : '服务暂时不可用，请稍后再试。');
  }
};
