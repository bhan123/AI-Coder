const assert = require('node:assert/strict');
const test = require('node:test');
const Module = require('node:module');
const path = require('node:path');

const entryPath = path.resolve(__dirname, '../cloudfunctions/operations-api/index.js');

async function withOperationsApi(openId, run) {
  const command = { lte: (value) => ({ $lte: value }) };
  const counts = { couples: 2, relationship_records: 8, notification_outbox: 3, privacy_requests: 5 };
  const db = {
    command,
    collection(name) {
      return { where() { return this; }, count: async () => ({ total: counts[name] || 0 }) };
    },
  };
  const sdk = { DYNAMIC_CURRENT_ENV: 'test', init() {}, database: () => db, getWXContext: () => ({ OPENID: openId }) };
  const originalLoad = Module._load;
  const originalAdmins = process.env.ADMIN_OPENIDS;
  process.env.ADMIN_OPENIDS = 'operator-openid';
  delete require.cache[entryPath];
  Module._load = function mockLoad(request, parent, isMain) { return request === 'wx-server-sdk' ? sdk : originalLoad.call(this, request, parent, isMain); };
  try { return await run(require(entryPath)); }
  finally {
    Module._load = originalLoad;
    if (originalAdmins === undefined) delete process.env.ADMIN_OPENIDS;
    else process.env.ADMIN_OPENIDS = originalAdmins;
    delete require.cache[entryPath];
  }
}

test('运营指标接口只允许 OpenID 白名单访问，且只返回聚合计数', async () => {
  await withOperationsApi('other-openid', async (api) => {
    const denied = await api.main({ action: 'summary' });
    assert.equal(denied.ok, false);
    assert.match(denied.message, /没有查看运营指标/);
  });
  await withOperationsApi('operator-openid', async (api) => {
    const allowed = await api.main({ action: 'summary' });
    assert.equal(allowed.ok, true);
    assert.deepEqual(Object.keys(allowed.data).sort(), ['activeCouples', 'generatedAt', 'notificationAttention', 'pendingNotifications', 'privacyCleanupBacklog', 'relationshipRecords']);
    assert.equal(allowed.data.activeCouples, 2);
  });
});
