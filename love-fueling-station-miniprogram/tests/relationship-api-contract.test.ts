import assert from 'node:assert/strict';
import test from 'node:test';
import { parseCloudConnection, parseCloudRecordPage, parsePrivacyExport } from '../src/services/relationship-contract';

test('客户端校验云端记录并兼容旧版 _id 后统一输出 id', () => {
  const page = parseCloudRecordPage({
    records: [{
      _id: 'record-old',
      kind: 'care',
      authorId: 'partner-a',
      content: '认真准备了早餐',
      createdAt: '2026-08-20T00:00:00.000Z',
      status: 'pending',
      requestedPoints: 3,
    }],
    hasMore: false,
    nextCursor: null,
  });
  assert.equal(page.records[0].id, 'record-old');
});

test('客户端拒绝没有任何记录 ID 的云端响应', () => {
  assert.throws(() => parseCloudRecordPage({ records: [{ kind: 'care' }], hasMore: false, nextCursor: null }), /记录 ID/);
});

test('客户端接受已进入个人删除流程的连接状态', () => {
  assert.deepEqual(parseCloudConnection({ status: 'deletion_pending', deleteAfter: '2026-09-01T00:00:00.000Z' }), {
    status: 'deletion_pending',
    deleteAfter: '2026-09-01T00:00:00.000Z',
  });
});

test('隐私导出经过运行时校验而不是类型断言', () => {
  const value = parsePrivacyExport({
    exportedAt: '2026-08-20T00:00:00.000Z',
    retentionPolicy: { liveDeletionDays: 7, backupDeletionDays: 30 },
    profile: { displayName: '小满' },
    identities: [], consents: [], memberships: [], invites: [], authoredRecords: [], contributions: [], auditEvents: [], privacyRequests: [],
  });
  assert.equal(value.retentionPolicy.backupDeletionDays, 30);
  assert.throws(() => parsePrivacyExport({ exportedAt: 'bad' }), /数据导出/);
});
