const cloud = require('wx-server-sdk');

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV });
const db = cloud.database();
const command = db.command;

function success(data) { return { ok: true, data }; }
function fail(message) { return { ok: false, message }; }
function operatorOpenIds() { return new Set((process.env.ADMIN_OPENIDS || '').split(',').map((value) => value.trim()).filter(Boolean)); }
function assertOperator() {
  const openId = cloud.getWXContext().OPENID;
  if (!openId || !operatorOpenIds().has(openId)) throw new Error('你没有查看运营指标的权限。');
}

async function summary() {
  assertOperator();
  const now = new Date().toISOString();
  const [activeCouples, relationshipRecords, pending, retryWait, retryExhausted, sentUnconfirmed, scheduled, primaryDeleted] = await Promise.all([
    db.collection('couples').where({ status: 'active' }).count(),
    db.collection('relationship_records').count(),
    db.collection('notification_outbox').where({ status: 'pending' }).count(),
    db.collection('notification_outbox').where({ status: 'retry_wait', retryAfter: command.lte(now) }).count(),
    db.collection('notification_outbox').where({ status: 'retry_exhausted' }).count(),
    db.collection('notification_outbox').where({ status: 'sent_unconfirmed' }).count(),
    db.collection('privacy_requests').where({ status: 'scheduled' }).count(),
    db.collection('privacy_requests').where({ status: 'primary_deleted' }).count(),
  ]);
  return success({ activeCouples: activeCouples.total, relationshipRecords: relationshipRecords.total, pendingNotifications: pending.total + retryWait.total, notificationAttention: retryExhausted.total + sentUnconfirmed.total, privacyCleanupBacklog: scheduled.total + primaryDeleted.total, generatedAt: now });
}

exports.main = async (event) => {
  try {
    if (event.action === 'summary') return await summary();
    return fail('不支持的操作。');
  } catch (error) {
    console.error('[operations-api]', error);
    return fail(error instanceof Error ? error.message : '暂时无法读取运营指标。');
  }
};
