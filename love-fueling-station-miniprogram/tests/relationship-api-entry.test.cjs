const assert = require('node:assert/strict');
const test = require('node:test');
const Module = require('node:module');
const path = require('node:path');

const entryPath = path.resolve(__dirname, '../cloudfunctions/relationship-api/index.js');

function createCloudMock({ hasConsent = true } = {}) {
  const calls = { securityChecks: 0, recordWhere: [] };
  const command = {
    lt: (value) => ({ $lt: value }),
    lte: (value) => ({ $lte: value }),
    or: (conditions) => ({ $or: conditions }),
    remove: () => ({ $remove: true }),
  };

  function documentData(collectionName) {
    if (collectionName === 'user_identities') return { userId: 'user-a' };
    if (collectionName === 'user_pairing_locks') return { userId: 'user-a', activeCoupleId: 'couple-a' };
    if (collectionName === 'privacy_consents') return hasConsent ? { userId: 'user-a' } : null;
    if (collectionName === 'users') return { status: 'active', displayName: '小满' };
    if (collectionName === 'couples') return { _id: 'couple-a', status: 'active', memberIds: ['user-a', 'user-b'] };
    return null;
  }

  function rowsFor(collectionName, query) {
    if (collectionName === 'memberships') return [{ coupleId: 'couple-a', userId: 'user-a', partnerId: 'partner-a', status: 'active' }];
    if (collectionName === 'relationship_records') {
      calls.recordWhere.push(query);
      return [];
    }
    return [];
  }

  function queryChain(collectionName, query) {
    return {
      where(nextQuery) { return queryChain(collectionName, nextQuery); },
      orderBy() { return this; },
      limit() { return this; },
      skip() { return this; },
      async get() { return { data: rowsFor(collectionName, query) }; },
      async update() { return { stats: { updated: 0 } }; },
      async count() { return { total: 0 }; },
    };
  }

  const db = {
    command,
    collection(collectionName) {
      return {
        doc() {
          return {
            async get() { return { data: documentData(collectionName) }; },
            async update() { return { stats: { updated: 1 } }; },
            async remove() { return { stats: { removed: 1 } }; },
          };
        },
        where(query) { return queryChain(collectionName, query); },
        async add() { return { _id: 'created' }; },
      };
    },
    async runTransaction() { throw new Error('transaction should not start'); },
  };

  return {
    calls,
    sdk: {
      DYNAMIC_CURRENT_ENV: 'test',
      init() {},
      database: () => db,
      getWXContext: () => ({ OPENID: 'openid-a', APPID: 'appid-a' }),
      openapi: {
        security: {
          async msgSecCheck() {
            calls.securityChecks += 1;
            return { result: { suggest: 'pass' } };
          },
        },
      },
    },
  };
}

async function withRelationshipApi(options, run) {
  const { sdk, calls } = createCloudMock(options);
  const originalLoad = Module._load;
  delete require.cache[entryPath];
  Module._load = function loadWithCloudMock(request, parent, isMain) {
    if (request === 'wx-server-sdk') return sdk;
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    const relationshipApi = require(entryPath);
    return await run(relationshipApi, calls);
  } finally {
    Module._load = originalLoad;
    delete require.cache[entryPath];
  }
}

test('云函数主入口能加载游标分页，且 command 来自 CloudBase 数据库命令对象', async () => {
  await withRelationshipApi({ hasConsent: true }, async (relationshipApi, calls) => {
    const result = await relationshipApi.main({ action: 'listRecords', cursor: null });
    assert.equal(result.ok, true);
    assert.deepEqual(calls.recordWhere, [{ coupleId: 'couple-a' }]);
  });
});

test('隐私同意失效时，记录文本不会先发送给内容安全接口', async () => {
  await withRelationshipApi({ hasConsent: false }, async (relationshipApi, calls) => {
    const result = await relationshipApi.main({
      action: 'createRecord',
      kind: 'care',
      content: '认真准备了晚饭',
      points: 3,
      operationId: 'op-12345678',
    });
    assert.equal(result.ok, false);
    assert.match(result.message, /隐私说明已更新/);
    assert.equal(calls.securityChecks, 0);
  });
});
