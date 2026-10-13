const assert = require('node:assert/strict');
const test = require('node:test');
const Module = require('node:module');
const path = require('node:path');

const entryPath = path.resolve(__dirname, '../cloudfunctions/notification-dispatch/index.js');

function createDatabase() {
  const rows = {
    notification_outbox: [{ _id: 'notice-1', coupleId: 'couple-1', recipientUserId: 'user-b', status: 'pending', attempts: 0, createdAt: '2026-08-27T00:00:00.000Z' }],
    memberships: [{ _id: 'member-1', coupleId: 'couple-1', userId: 'user-b', status: 'active' }],
    subscription_grants: [{ _id: 'grant-1', userId: 'user-b', templateId: 'template_12345678', remainingQuota: 1, acceptedAt: '2026-08-27T00:00:00.000Z' }],
    user_identities: [{ _id: 'identity-1', userId: 'user-b', status: 'active', openId: 'openid-b', createdAt: '2026-08-27T00:00:00.000Z' }],
  };
  const command = { gt: (value) => ({ $gt: value }), lte: (value) => ({ $lte: value }), inc: (value) => ({ $inc: value }), remove: () => ({ $remove: true }) };
  const matches = (item, query) => Object.entries(query || {}).every(([key, expected]) => {
    if (expected && typeof expected === 'object' && '$gt' in expected) return item[key] > expected.$gt;
    if (expected && typeof expected === 'object' && '$lte' in expected) return item[key] <= expected.$lte;
    return item[key] === expected;
  });
  const apply = (item, patch) => Object.entries(patch).forEach(([key, value]) => {
    if (value && typeof value === 'object' && '$inc' in value) item[key] = (item[key] || 0) + value.$inc;
    else if (value && typeof value === 'object' && '$remove' in value) delete item[key];
    else item[key] = value;
  });
  const collection = (name) => ({
    doc(id) {
      const current = () => (rows[name] || []).find((item) => item._id === id);
      return { get: async () => ({ data: current() || null }), update: async ({ data }) => { apply(current(), data); return { stats: { updated: 1 } }; } };
    },
    where(query) {
      const current = () => (rows[name] || []).filter((item) => matches(item, query));
      return {
        orderBy() { return this; }, limit() { return this; },
        get: async () => ({ data: current() }),
        update: async ({ data }) => { current().forEach((item) => apply(item, data)); return { stats: { updated: current().length } }; },
        count: async () => ({ total: current().length }),
      };
    },
  });
  return { command, collection, runTransaction: async (worker) => worker({ collection }) , rows };
}

test('通知派发成功后消费一次授权并进入 sent 终态', async () => {
  const database = createDatabase();
  let sends = 0;
  const sdk = { DYNAMIC_CURRENT_ENV: 'test', init() {}, database: () => database, openapi: { subscribeMessage: { send: async ({ touser }) => { sends += 1; assert.equal(touser, 'openid-b'); } } } };
  const originalLoad = Module._load;
  const originalTemplate = process.env.SUBSCRIBE_TEMPLATE_ID;
  process.env.SUBSCRIBE_TEMPLATE_ID = 'template_12345678';
  delete require.cache[entryPath];
  Module._load = function mockLoad(request, parent, isMain) { return request === 'wx-server-sdk' ? sdk : originalLoad.call(this, request, parent, isMain); };
  try {
    const dispatch = require(entryPath);
    const result = await dispatch.main();
    assert.equal(result.ok, true);
    assert.equal(sends, 1);
    assert.equal(database.rows.notification_outbox[0].status, 'sent');
    assert.equal(database.rows.subscription_grants[0].remainingQuota, 0);
  } finally {
    Module._load = originalLoad;
    if (originalTemplate === undefined) delete process.env.SUBSCRIBE_TEMPLATE_ID;
    else process.env.SUBSCRIBE_TEMPLATE_ID = originalTemplate;
    delete require.cache[entryPath];
  }
});
