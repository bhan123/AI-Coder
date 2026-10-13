const crypto = require('crypto');
const cloud = require('wx-server-sdk');
const { cleanupPhase } = require('./lib/retention');
const { personalRecordScrubPlan, personalReferenceScrubPlan } = require('./lib/personal-scrub');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const command = db.command;
const DEFAULT_BATCH_SIZE = 20;
const MAX_BATCH_SIZE = 100;
const NOTIFICATION_RETENTION_DAYS = 30;

function hash(value) { return crypto.createHash('sha256').update(String(value)).digest('hex'); }
function now() { return new Date().toISOString(); }
function cleanupBatchSize() {
  const configured = Number.parseInt(process.env.PRIVACY_CLEANUP_BATCH_SIZE || '', 10);
  if (!Number.isInteger(configured) || configured < 1) return DEFAULT_BATCH_SIZE;
  return Math.min(configured, MAX_BATCH_SIZE);
}
async function dueBacklog(currentIso) {
  const [primary, backup, pending] = await Promise.all([
    db.collection('privacy_requests').where({ status: 'scheduled', executeAfter: command.lte(currentIso) }).count(),
    db.collection('privacy_requests').where({ status: 'primary_deleted', backupDeleteAfter: command.lte(currentIso) }).count(),
    db.collection('privacy_requests').where({ status: 'pending_partner_confirmation', expiresAt: command.lte(currentIso) }).count(),
  ]);
  return { primary: primary.total, backup: backup.total, pending: pending.total, total: primary.total + backup.total + pending.total };
}

async function readAll(collectionName, query) {
  const rows = [];
  let offset = 0;
  while (true) {
    const result = await db.collection(collectionName).where(query).skip(offset).limit(100).get();
    rows.push(...result.data);
    if (result.data.length < 100) return rows;
    offset += result.data.length;
  }
}

async function removeDocuments(collectionName, query, keepId = null) {
  while (true) {
    const result = await db.collection(collectionName).where(query).limit(100).get();
    const documents = result.data.filter((item) => item._id !== keepId);
    if (documents.length === 0) return;
    await Promise.all(documents.map((item) => db.collection(collectionName).doc(item._id).remove()));
    if (result.data.length < 100) return;
  }
}

async function removeDocument(collectionName, documentId) {
  if (!documentId) return;
  await db.collection(collectionName).doc(documentId).remove().catch(() => null);
}

function recordFileIds(record) {
  return Array.isArray(record && record.attachments) ? record.attachments.map((item) => item && item.fileId).filter((fileId) => typeof fileId === 'string') : [];
}
async function deleteCloudFiles(fileIds) {
  if (!fileIds.length) return;
  if (typeof cloud.deleteFile !== 'function') throw new Error('云存储删除能力尚未配置。');
  for (let index = 0; index < fileIds.length; index += 50) {
    const result = await cloud.deleteFile({ fileList: fileIds.slice(index, index + 50) });
    if (Array.isArray(result.fileList) && result.fileList.some((item) => item.status !== 0)) throw new Error('部分附件文件未能删除。');
  }
}

async function applyScrubPlan(collectionName, documentId, plan) {
  if (!plan || plan.action !== 'update') return;
  const data = { ...(plan.set || {}) };
  for (const field of plan.unset || []) data[field] = command.remove();
  if (Object.keys(data).length === 0) return;
  await db.collection(collectionName).doc(documentId).update({ data });
}

async function deletePersonalPrimary(request) {
  const userId = request.userId;
  if (!userId) throw new Error(`个人删除请求 ${request._id} 缺少 userId。`);
  const memberships = await readAll('memberships', { userId });
  for (const membership of memberships) {
    const records = await readAll('relationship_records', { coupleId: membership.coupleId });
    for (const record of records) {
      const plan = personalRecordScrubPlan(record, membership.partnerId);
      if (plan.action === 'delete') {
        await deleteCloudFiles(recordFileIds(record));
        await removeDocument('relationship_records', record._id);
      }
      else await applyScrubPlan('relationship_records', record._id, plan);
    }
    const coupleResult = await db.collection('couples').doc(membership.coupleId).get().catch(() => null);
    if (coupleResult && coupleResult.data) {
      const plan = personalReferenceScrubPlan(coupleResult.data, userId);
      plan.set.updatedAt = now();
      await applyScrubPlan('couples', membership.coupleId, plan);
    }
  }

  await removeDocuments('pair_invites', { creatorUserId: userId });
  const acceptedInvites = await readAll('pair_invites', { acceptedBy: userId });
  for (const invite of acceptedInvites) await applyScrubPlan('pair_invites', invite._id, personalReferenceScrubPlan(invite, userId));

  const requestedPrivacy = await readAll('privacy_requests', { requestedBy: userId });
  const confirmedPrivacy = await readAll('privacy_requests', { confirmedBy: userId });
  const privacyReferences = [...new Map([...requestedPrivacy, ...confirmedPrivacy].map((item) => [item._id, item])).values()];
  for (const privacyRequest of privacyReferences) {
    if (privacyRequest._id !== request._id) await applyScrubPlan('privacy_requests', privacyRequest._id, personalReferenceScrubPlan(privacyRequest, userId));
  }

  await removeDocuments('data_backups', { userId });
  await removeDocuments('user_identities', { userId });
  await removeDocuments('memberships', { userId });
  await removeDocuments('audit_events', { actorUserId: userId });
  await removeDocuments('idempotency_keys', { userId });
  await removeDocuments('privacy_consents', { userId });
  await removeDocuments('rate_limits', { userId });
  await removeDocuments('subscription_grants', { userId });
  await removeDocuments('media_upload_tickets', { userId });
  await removeDocuments('notification_outbox', { actorUserId: userId });
  await removeDocuments('notification_outbox', { recipientUserId: userId });
  await removeDocument('user_pairing_locks', userId);
  await removeDocument('users', userId);

  await db.collection('privacy_requests').doc(request._id).update({ data: {
    status: 'primary_deleted',
    primaryDeletedAt: now(),
    targetHash: hash(`user:${userId}`),
    userId: null,
    coupleId: null,
  } });
}

async function deleteSpacePrimary(request) {
  const coupleId = request.coupleId;
  if (!coupleId) throw new Error(`共同空间删除请求 ${request._id} 缺少 coupleId。`);
  const records = await readAll('relationship_records', { coupleId });
  await deleteCloudFiles(records.flatMap(recordFileIds));
  await removeDocuments('relationship_records', { coupleId });
  await removeDocuments('couple_settings', { _id: coupleId });
  await removeDocuments('memberships', { coupleId });
  await removeDocuments('audit_events', { coupleId });
  await removeDocuments('privacy_requests', { coupleId }, request._id);
  await removeDocuments('media_upload_tickets', { coupleId });
  await removeDocuments('notification_outbox', { coupleId });
  await removeDocument('couples', coupleId);
  await db.collection('privacy_requests').doc(request._id).update({ data: {
    status: 'primary_deleted',
    primaryDeletedAt: now(),
    targetHash: hash(`couple:${coupleId}`),
    coupleId: null,
    requestedBy: null,
    confirmedBy: null,
  } });
}

async function deleteAppBackups(request) {
  await removeDocuments('data_backups', { privacyRequestId: request._id });
  await db.collection('privacy_deletion_receipts').add({ data: {
    _id: `receipt_${hash(request._id).slice(0, 40)}`,
    requestHash: hash(request._id),
    type: request.type,
    primaryDeletedAt: request.primaryDeletedAt || null,
    appBackupsDeletedAt: now(),
    createdAt: now(),
  } }).catch(() => null);
  await removeDocument('privacy_requests', request._id);
}

async function cleanupExpiredIdempotency() {
  const expired = await db.collection('idempotency_keys').where({ expiresAt: command.lte(now()) }).limit(100).get();
  await Promise.all(expired.data.map((item) => db.collection('idempotency_keys').doc(item._id).remove()));
  return expired.data.length;
}

async function cleanupExpiredRateLimits() {
  const expired = await db.collection('rate_limits').where({ expiresAt: command.lte(now()) }).limit(100).get();
  await Promise.all(expired.data.map((item) => db.collection('rate_limits').doc(item._id).remove()));
  return expired.data.length;
}

async function cleanupExpiredMediaTickets() {
  const expired = await db.collection('media_upload_tickets').where({ status: 'active', expiresAt: command.lte(now()) }).limit(100).get();
  for (const ticket of expired.data) {
    await deleteCloudFiles(Array.isArray(ticket.fileIds) ? ticket.fileIds.filter((item) => typeof item === 'string') : []);
    await removeDocument('media_upload_tickets', ticket._id);
  }
  return expired.data.length;
}

async function cleanupExpiredNotifications() {
  const cutoff = new Date(Date.now() - NOTIFICATION_RETENTION_DAYS * 86400000).toISOString();
  const groups = [
    ['sent', 'sentAt'], ['sent_unconfirmed', 'sentUnconfirmedAt'], ['retry_exhausted', 'failedAt'],
    ['skipped_space_closed', 'handledAt'], ['skipped_no_permission', 'handledAt'],
  ];
  let removed = 0;
  for (const [status, timestamp] of groups) {
    const expired = await db.collection('notification_outbox').where({ status, [timestamp]: command.lte(cutoff) }).limit(100).get();
    await Promise.all(expired.data.map((item) => db.collection('notification_outbox').doc(item._id).remove()));
    removed += expired.data.length;
  }
  return removed;
}

exports.main = async () => {
  const currentTime = Date.now();
  const currentIso = new Date(currentTime).toISOString();
  const batchSize = cleanupBatchSize();
  const backlogBefore = await dueBacklog(currentIso);
  const primaryDue = await db.collection('privacy_requests').where({ status: 'scheduled', executeAfter: command.lte(currentIso) }).limit(batchSize).get();
  const remainingCapacity = Math.max(0, batchSize - primaryDue.data.length);
  const backupDue = remainingCapacity > 0
    ? await db.collection('privacy_requests').where({ status: 'primary_deleted', backupDeleteAfter: command.lte(currentIso) }).limit(remainingCapacity).get()
    : { data: [] };
  const pendingCapacity = Math.max(0, remainingCapacity - backupDue.data.length);
  const expiredPending = pendingCapacity > 0
    ? await db.collection('privacy_requests').where({ status: 'pending_partner_confirmation', expiresAt: command.lte(currentIso) }).limit(pendingCapacity).get()
    : { data: [] };
  const candidates = [...primaryDue.data, ...backupDue.data, ...expiredPending.data];
  const processed = [];
  const failed = [];
  for (const request of candidates) {
    try {
      const phase = cleanupPhase(request, currentTime);
      if (phase === 'primary') {
        if (request.type === 'personal_deletion') await deletePersonalPrimary(request);
        else if (request.type === 'space_deletion') await deleteSpacePrimary(request);
        else throw new Error(`未知删除类型：${request.type}`);
        processed.push({ requestId: request._id, phase });
      } else if (phase === 'backup') {
        await deleteAppBackups(request);
        processed.push({ requestId: request._id, phase });
      } else if (phase === 'expire_pending') {
        await removeDocument('privacy_requests', request._id);
        processed.push({ requestId: request._id, phase });
      }
    } catch (error) {
      console.error('[privacy-cleanup]', request._id, error);
      failed.push({ requestId: request._id, message: error instanceof Error ? error.message : 'unknown error' });
    }
  }
  const expiredIdempotencyKeys = await cleanupExpiredIdempotency();
  const expiredRateLimits = await cleanupExpiredRateLimits();
  const expiredMediaTickets = await cleanupExpiredMediaTickets();
  const expiredNotifications = await cleanupExpiredNotifications();
  const backlogAfter = await dueBacklog(currentIso);
  return {
    ok: failed.length === 0,
    processed,
    failed,
    batchSize,
    backlogBefore,
    backlogAfter,
    requiresAttention: failed.length > 0 || backlogAfter.total > 0,
    expiredIdempotencyKeys,
    expiredRateLimits,
    expiredMediaTickets,
    expiredNotifications,
  };
};
