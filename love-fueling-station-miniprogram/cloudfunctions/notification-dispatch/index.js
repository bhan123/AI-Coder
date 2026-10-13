const cloud = require('wx-server-sdk');
const { buildTemplateData } = require('./lib/messages');
const { canReserve, isSendingLeaseExpired } = require('./lib/delivery-state');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const command = db.command;

const templateId = process.env.SUBSCRIBE_TEMPLATE_ID || '';
const eventField = process.env.SUBSCRIBE_EVENT_FIELD || 'thing1';
const timeField = process.env.SUBSCRIBE_TIME_FIELD || 'time2';
const miniProgramState = process.env.MINIPROGRAM_ENV_VERSION || 'trial';
const batchSize = Math.min(Math.max(Number.parseInt(process.env.NOTIFICATION_BATCH_SIZE || '20', 10) || 20, 1), 50);
const maxAttempts = Math.min(Math.max(Number.parseInt(process.env.NOTIFICATION_MAX_ATTEMPTS || '3', 10) || 3, 1), 10);
const sendingLeaseMs = Math.min(Math.max(Number.parseInt(process.env.NOTIFICATION_SENDING_LEASE_MS || String(5 * 60 * 1000), 10) || 5 * 60 * 1000, 60 * 1000), 60 * 60 * 1000);

async function activeIdentity(userId) {
  const result = await db.collection('user_identities').where({ userId, status: 'active' }).orderBy('createdAt', 'desc').limit(1).get();
  return result.data[0] || null;
}

async function reserve(outbox) {
  return db.runTransaction(async (transaction) => {
    const current = await transaction.collection('notification_outbox').doc(outbox._id).get();
    const currentTime = Date.now();
    if (current.data && current.data.status === 'sending' && isSendingLeaseExpired(current.data.sendingAt, currentTime, sendingLeaseMs)) {
      // 云函数可能已向微信提交成功但在落库前中断。为避免重复打扰，转为人工可见的终态而不重发。
      await transaction.collection('notification_outbox').doc(outbox._id).update({ data: {
        status: 'sent_unconfirmed',
        sentUnconfirmedAt: new Date(currentTime).toISOString(),
        lastError: 'sending lease expired before delivery state was confirmed',
      } });
      return { skipped: true, reason: 'sending_state_uncertain' };
    }
    const decision = canReserve(current.data, currentTime, sendingLeaseMs, maxAttempts);
    if (!decision.allowed) {
      if (decision.reason === 'retry_exhausted' && current.data) await transaction.collection('notification_outbox').doc(outbox._id).update({ data: { status: 'retry_exhausted', failedAt: new Date(currentTime).toISOString(), lastError: current.data.lastError || 'retry attempts exhausted' } });
      return { skipped: true, reason: decision.reason };
    }
    const membership = await transaction.collection('memberships').where({ coupleId: current.data.coupleId, userId: current.data.recipientUserId, status: 'active' }).limit(1).get();
    if (!membership.data[0]) {
      await transaction.collection('notification_outbox').doc(outbox._id).update({ data: { status: 'skipped_space_closed', handledAt: new Date().toISOString() } });
      return { skipped: true, reason: 'space_closed' };
    }
    const grants = await transaction.collection('subscription_grants').where({ userId: current.data.recipientUserId, templateId, remainingQuota: command.gt(0) }).orderBy('acceptedAt', 'asc').limit(1).get();
    const grant = grants.data[0];
    if (!grant) {
      await transaction.collection('notification_outbox').doc(outbox._id).update({ data: { status: 'skipped_no_permission', handledAt: new Date().toISOString() } });
      return { skipped: true, reason: 'no_quota' };
    }
    const sendingAt = new Date(currentTime).toISOString();
    await transaction.collection('subscription_grants').doc(grant._id).update({ data: { remainingQuota: command.inc(-1), reservedAt: sendingAt } });
    await transaction.collection('notification_outbox').doc(outbox._id).update({ data: { status: 'sending', grantId: grant._id, attempts: (current.data.attempts || 0) + 1, sendingAt, retryAfter: command.remove() } });
    return { outbox: current.data, grantId: grant._id };
  });
}

async function restoreQuota(outbox, grantId, message) {
  await db.runTransaction(async (transaction) => {
    await transaction.collection('subscription_grants').doc(grantId).update({ data: { remainingQuota: command.inc(1), lastFailedAt: new Date().toISOString() } });
    const attempts = (outbox.attempts || 0) + 1;
    const failedAt = new Date().toISOString();
    const exhausted = attempts >= maxAttempts;
    await transaction.collection('notification_outbox').doc(outbox._id).update({ data: exhausted
      ? { status: 'retry_exhausted', lastError: String(message || 'send failed').slice(0, 240), failedAt }
      : { status: 'retry_wait', lastError: String(message || 'send failed').slice(0, 240), retryAfter: new Date(Date.now() + 5 * 60 * 1000).toISOString() },
    });
  });
}

async function markSentUnconfirmed(outbox, message) {
  await db.collection('notification_outbox').doc(outbox._id).update({ data: {
    status: 'sent_unconfirmed',
    sentUnconfirmedAt: new Date().toISOString(),
    lastError: String(message || 'send state could not be persisted').slice(0, 240),
  } });
}

async function dispatchOne(outbox) {
  const reservation = await reserve(outbox);
  if (reservation.skipped) return { id: outbox._id, status: reservation.reason };
  const identity = await activeIdentity(reservation.outbox.recipientUserId);
  if (!identity || !identity.openId) {
    await restoreQuota(reservation.outbox, reservation.grantId, 'recipient identity unavailable');
    return { id: outbox._id, status: 'identity_unavailable' };
  }
  try {
    await cloud.openapi.subscribeMessage.send({
      touser: identity.openId,
      templateId,
      page: 'pages/history/index',
      data: buildTemplateData(reservation.outbox.type, reservation.outbox.createdAt, eventField, timeField),
      miniprogramState: miniProgramState,
      lang: 'zh_CN',
    });
    try {
      await db.collection('notification_outbox').doc(outbox._id).update({ data: { status: 'sent', sentAt: new Date().toISOString() } });
    } catch (error) {
      // 微信侧已接受发送，不能重试以免重复打扰；保留为可告警的终态。
      try {
        await markSentUnconfirmed(outbox, error && (error.errMsg || error.message));
        return { id: outbox._id, status: 'sent_unconfirmed' };
      } catch (markError) {
        console.error('[notification-dispatch] sent but state persistence failed', markError);
        return { id: outbox._id, status: 'sent_state_unknown' };
      }
    }
    return { id: outbox._id, status: 'sent' };
  } catch (error) {
    await restoreQuota(reservation.outbox, reservation.grantId, error && (error.errMsg || error.message));
    return { id: outbox._id, status: 'retrying' };
  }
}

exports.main = async () => {
  if (!templateId) return { ok: false, reason: 'SUBSCRIBE_TEMPLATE_ID is not configured', processed: [] };
  const pending = await db.collection('notification_outbox').where({ status: 'pending' }).orderBy('createdAt', 'asc').limit(batchSize).get();
  const remaining = Math.max(0, batchSize - pending.data.length);
  const retrying = remaining > 0
    ? await db.collection('notification_outbox').where({ status: 'retry_wait', retryAfter: command.lte(new Date().toISOString()) }).orderBy('retryAfter', 'asc').limit(remaining).get()
    : { data: [] };
  const afterRetry = Math.max(0, batchSize - pending.data.length - retrying.data.length);
  const staleSending = afterRetry > 0
    ? await db.collection('notification_outbox').where({ status: 'sending', sendingAt: command.lte(new Date(Date.now() - sendingLeaseMs).toISOString()) }).orderBy('sendingAt', 'asc').limit(afterRetry).get()
    : { data: [] };
  const result = { data: [...pending.data, ...retrying.data, ...staleSending.data] };
  const processed = [];
  for (const outbox of result.data) processed.push(await dispatchOne(outbox));
  const requiresAttention = processed.some((item) => ['retry_exhausted', 'sent_unconfirmed', 'sent_state_unknown', 'sending_state_uncertain'].includes(item.status));
  return { ok: true, processed, requiresAttention };
};
