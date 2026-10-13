const assert = require('node:assert/strict');
const test = require('node:test');
const { assertPairingAvailable, responsePatch, careReviewPatch, ruleDecisionPatch, toClientRecord } = require('../cloudfunctions/relationship-api/lib/contracts');
const { executeMutationInTransaction, withCachedMutationEnvelope } = require('../cloudfunctions/relationship-api/lib/mutation');
const { cleanupPhase, closePendingRequestPatch } = require('../cloudfunctions/privacy-cleanup/lib/retention');
const { buildPersonalRecordExport } = require('../cloudfunctions/relationship-api/lib/privacy');
const { personalRecordScrubPlan, personalReferenceScrubPlan } = require('../cloudfunctions/privacy-cleanup/lib/personal-scrub');
const { encodeRecordCursor, decodeRecordCursor, recordCursorWhere, exportCursorWhere, nextExportCursor } = require('../cloudfunctions/relationship-api/lib/pagination');
const { nextRateLimitState } = require('../cloudfunctions/relationship-api/lib/rate-limit');

test('云端记录必须把数据库 _id 映射为前端 id', () => {
  const result = toClientRecord({
    _id: 'record_123',
    coupleId: 'couple_1',
    kind: 'care',
    authorId: 'partner-a',
    content: '准备好了晚饭',
    createdAt: '2026-08-20T00:00:00.000Z',
    status: 'pending',
  });

  assert.equal(result.id, 'record_123');
  assert.equal('_id' in result, false);
});

test('接受邀请时创建者和接受者都必须仍处于未配对状态', () => {
  const common = {
    invite: { status: 'active', creatorUserId: 'user-a', expiresAt: '2026-08-21T00:00:00.000Z' },
    accepterLock: { userId: 'user-c', activeCoupleId: null },
    currentTime: Date.parse('2026-08-20T00:00:00.000Z'),
  };
  assert.throws(() => assertPairingAvailable({ ...common, creatorLock: { userId: 'user-a', activeCoupleId: 'couple-b' } }), /创建者已经加入/);
  assert.doesNotThrow(() => assertPairingAvailable({ ...common, creatorLock: { userId: 'user-a', activeCoupleId: null } }));
});

test('回应只允许从待回应状态写入一次', () => {
  const record = { kind: 'feeling', authorId: 'partner-a', status: 'awaiting_response' };
  const patch = responsePatch(record, 'partner-b', '我听见了', '2026-08-20T00:00:00.000Z');
  assert.equal(patch.status, 'responded');
  assert.throws(() => responsePatch({ ...record, status: 'responded' }, 'partner-b', '覆盖回应', '2026-08-20T00:01:00.000Z'), /不能覆盖/);
});

test('行动审批只能由对方进行一次，且审批分数由对方决定', () => {
  const record = { kind: 'care', authorId: 'partner-a', status: 'pending' };
  assert.deepEqual(careReviewPatch(record, 'partner-b', 'approved', 5, '2026-08-20T00:00:00.000Z'), {
    status: 'approved', reviewedBy: 'partner-b', reviewedAt: '2026-08-20T00:00:00.000Z', effectivePoints: 5,
  });
  assert.throws(() => careReviewPatch({ ...record, status: 'approved' }, 'partner-b', 'approved', 3, 'time'), /不能重复/);
});

test('共同约定只能从 pending 状态决定一次', () => {
  const record = { kind: 'rule', authorId: 'partner-a', status: 'pending' };
  assert.equal(ruleDecisionPatch(record, 'partner-b', true, '2026-08-20T00:00:00.000Z').status, 'confirmed');
  assert.throws(() => ruleDecisionPatch({ ...record, status: 'declined' }, 'partner-b', true, '2026-08-20T00:01:00.000Z'), /不能重复/);
});

test('业务写入、审计和幂等凭证使用同一个事务且审计失败会中止', async () => {
  const transaction = { marker: 'same-transaction' };
  const calls = [];
  await assert.rejects(() => executeMutationInTransaction({
    transaction,
    previousResult: async () => null,
    worker: async (tx) => { calls.push(['business', tx]); return { data: null, coupleId: 'couple-1', auditType: 'care_created' }; },
    addAudit: async (tx) => { calls.push(['audit', tx]); throw new Error('audit failed'); },
    saveIdempotency: async (tx) => { calls.push(['idempotency', tx]); },
  }), /audit failed/);
  assert.deepEqual(calls.map(([name]) => name), ['business', 'audit']);
  assert.equal(calls.every(([, tx]) => tx === transaction), true);
});

test('幂等凭证即使缓存结果为 null 也不能再次执行写入', async () => {
  let writes = 0;
  const result = await executeMutationInTransaction({
    transaction: {},
    previousResult: async () => ({ found: true, value: null }),
    worker: async () => { writes += 1; return { data: null }; },
    addAudit: async () => {},
    saveIdempotency: async () => {},
  });
  assert.equal(result, null);
  assert.equal(writes, 0);
});

test('隐私删除严格区分业务主库清理与应用备份清理期限', () => {
  const request = {
    status: 'scheduled',
    executeAfter: '2026-08-27T00:00:00.000Z',
    backupDeleteAfter: '2026-09-19T00:00:00.000Z',
  };
  assert.equal(cleanupPhase(request, Date.parse('2026-08-26T23:59:59.000Z')), 'wait');
  assert.equal(cleanupPhase(request, Date.parse('2026-08-27T00:00:00.000Z')), 'primary');
  assert.equal(cleanupPhase({ ...request, status: 'primary_deleted' }, Date.parse('2026-09-18T00:00:00.000Z')), 'wait');
  assert.equal(cleanupPhase({ ...request, status: 'primary_deleted' }, Date.parse('2026-09-19T00:00:00.000Z')), 'backup');
});

test('本人导出不因历史 membership 重新获得伴侣内容', () => {
  const records = [
    { _id: 'own', coupleId: 'couple-old', authorId: 'partner-a', kind: 'feeling', content: '我自己的感受', status: 'responded', response: '伴侣回应' },
    { _id: 'partner', coupleId: 'couple-old', authorId: 'partner-b', kind: 'feeling', content: '伴侣的私密内容', status: 'responded', response: '我写的回应', respondedBy: 'partner-a', respondedAt: '2026-08-20T00:00:00.000Z' },
  ];
  const result = buildPersonalRecordExport(records, [{ coupleId: 'couple-old', partnerId: 'partner-a', status: 'revoked' }]);
  assert.deepEqual(result.authoredRecords.map((item) => item.id), ['own']);
  assert.equal(JSON.stringify(result).includes('伴侣的私密内容'), false);
  assert.deepEqual(result.contributions, [{ recordId: 'partner', coupleId: 'couple-old', type: 'response', response: '我写的回应', respondedAt: '2026-08-20T00:00:00.000Z' }]);
});

function applyScrub(document, plan) {
  if (plan.action === 'delete') return null;
  const next = { ...document, ...plan.set };
  for (const field of plan.unset || []) delete next[field];
  return next;
}

test('本人删除会擦除跨记录和跨集合的全部本人贡献字段', () => {
  const response = applyScrub(
    { _id: 'r1', kind: 'feeling', authorId: 'partner-b', status: 'responded', response: '本人回应文本', respondedBy: 'partner-a', respondedAt: 'time' },
    personalRecordScrubPlan({ _id: 'r1', kind: 'feeling', authorId: 'partner-b', status: 'responded', response: '本人回应文本', respondedBy: 'partner-a', respondedAt: 'time' }, 'partner-a'),
  );
  assert.equal(JSON.stringify(response).includes('本人回应文本'), false);
  assert.equal(response.status, 'awaiting_response');

  const rule = applyScrub(
    { _id: 'r2', kind: 'rule', authorId: 'partner-b', status: 'confirmed', confirmedBy: 'partner-a', decidedAt: 'time' },
    personalRecordScrubPlan({ _id: 'r2', kind: 'rule', authorId: 'partner-b', status: 'confirmed', confirmedBy: 'partner-a', decidedAt: 'time' }, 'partner-a'),
  );
  assert.equal(rule.confirmedBy, undefined);
  assert.equal(rule.status, 'pending');

  const careReview = applyScrub(
    { _id: 'r3', kind: 'care', authorId: 'partner-b', status: 'approved', reviewedBy: 'partner-a', reviewedAt: 'time', effectivePoints: 5 },
    personalRecordScrubPlan({ _id: 'r3', kind: 'care', authorId: 'partner-b', status: 'approved', reviewedBy: 'partner-a', reviewedAt: 'time', effectivePoints: 5 }, 'partner-a'),
  );
  assert.equal(JSON.stringify(careReview).includes('partner-a'), false);
  assert.equal(careReview.status, 'pending');
  assert.equal(careReview.effectivePoints, undefined);

  const invite = applyScrub({ status: 'accepted', acceptedBy: 'user-a', acceptedAt: 'time' }, personalReferenceScrubPlan({ status: 'accepted', acceptedBy: 'user-a', acceptedAt: 'time' }, 'user-a'));
  const request = applyScrub({ status: 'pending_partner_confirmation', requestedBy: 'user-a', requestedByPartnerId: 'partner-a' }, personalReferenceScrubPlan({ status: 'pending_partner_confirmation', requestedBy: 'user-a', requestedByPartnerId: 'partner-a' }, 'user-a'));
  const couple = applyScrub({ memberIds: ['user-a', 'user-b'], closedBy: 'user-a' }, personalReferenceScrubPlan({ memberIds: ['user-a', 'user-b'], closedBy: 'user-a' }, 'user-a'));
  assert.equal(JSON.stringify({ invite, request, couple }).includes('user-a'), false);
  assert.equal(request.status, 'cancelled_by_personal_deletion');

  const scheduled = applyScrub(
    { status: 'scheduled', requestedBy: 'user-a', confirmedBy: 'user-b' },
    personalReferenceScrubPlan({ status: 'scheduled', requestedBy: 'user-a', confirmedBy: 'user-b' }, 'user-a'),
  );
  assert.equal(scheduled.status, 'scheduled');
  assert.equal(scheduled.requestedBy, undefined);
  assert.equal(scheduled.confirmedBy, 'user-b');
});

test('接受邀请丢包重试会先恢复幂等结果，不再查询已失效的邀请码', async () => {
  let invitationLookups = 0;
  const envelope = await withCachedMutationEnvelope({
    loadCached: async () => ({ found: true, value: { status: 'paired', coupleId: 'couple-1', viewerId: 'partner-b' } }),
    execute: async () => { invitationLookups += 1; throw new Error('不应查询邀请码'); },
  });
  assert.equal(envelope.ok, true);
  assert.equal(envelope.data.coupleId, 'couple-1');
  assert.equal(invitationLookups, 0);
});

test('共同删除待确认请求会过期，退出空间时也会被取消并匿名化', () => {
  const request = { status: 'pending_partner_confirmation', expiresAt: '2026-08-27T00:00:00.000Z', requestedBy: 'user-a', coupleId: 'couple-1' };
  assert.equal(cleanupPhase(request, Date.parse('2026-08-27T00:00:00.000Z')), 'expire_pending');
  const patch = closePendingRequestPatch('2026-08-21T00:00:00.000Z');
  assert.equal(patch.status, 'cancelled_space_closed');
  assert.deepEqual(patch.unset.sort(), ['confirmedBy', 'requestedBy', 'requestedByPartnerId'].sort());
});

test('历史记录使用 createdAt 与 _id 复合游标，不再使用 offset', () => {
  const cursor = encodeRecordCursor({ createdAt: '2026-08-20T00:00:00.000Z', _id: 'record-b' });
  assert.deepEqual(decodeRecordCursor(cursor), { createdAt: '2026-08-20T00:00:00.000Z', _id: 'record-b' });
  const command = {
    lt: (value) => ({ lt: value }),
    or: (conditions) => ({ or: conditions }),
  };
  assert.deepEqual(recordCursorWhere(command, 'couple-1', decodeRecordCursor(cursor)), {
    or: [
      { coupleId: 'couple-1', createdAt: { lt: '2026-08-20T00:00:00.000Z' } },
      { coupleId: 'couple-1', createdAt: '2026-08-20T00:00:00.000Z', _id: { lt: 'record-b' } },
    ],
  });
});

test('数据导出固定起点并使用 createdAt 与 _id 复合游标，不使用 offset', () => {
  const command = {
    lt: (value) => ({ lt: value }),
    lte: (value) => ({ lte: value }),
    or: (conditions) => ({ or: conditions }),
  };
  const first = exportCursorWhere(command, { userId: 'user-a' }, 'createdAt', '2026-08-20T00:00:00.000Z', null);
  assert.deepEqual(first, { userId: 'user-a', createdAt: { lte: '2026-08-20T00:00:00.000Z' } });
  const cursor = nextExportCursor({ _id: 'item-2', createdAt: '2026-08-19T00:00:00.000Z' }, 'createdAt');
  assert.deepEqual(exportCursorWhere(command, { userId: 'user-a' }, 'createdAt', '2026-08-20T00:00:00.000Z', cursor), {
    or: [
      { userId: 'user-a', createdAt: { lt: '2026-08-19T00:00:00.000Z' } },
      { userId: 'user-a', createdAt: '2026-08-19T00:00:00.000Z', _id: { lt: 'item-2' } },
    ],
  });
});

test('服务端频控在固定窗口达到上限后拒绝继续写入', () => {
  const rule = { limit: 2, windowMs: 60000 };
  const first = nextRateLimitState(null, 1000, rule);
  const second = nextRateLimitState(first.state, 2000, rule);
  const third = nextRateLimitState(second.state, 3000, rule);
  assert.equal(first.allowed, true);
  assert.equal(second.allowed, true);
  assert.equal(third.allowed, false);
  assert.equal(nextRateLimitState(third.state, 62000, rule).allowed, true);
});
