const assert = require('node:assert/strict');
const test = require('node:test');
const { canReserve, isSendingLeaseExpired } = require('../cloudfunctions/notification-dispatch/lib/delivery-state');

const NOW = Date.parse('2026-08-27T00:00:00.000Z');
const LEASE = 5 * 60 * 1000;

test('通知发送租约过期后可以恢复，未过期时不能并发重发', () => {
  assert.equal(isSendingLeaseExpired('2026-08-26T23:54:59.000Z', NOW, LEASE), true);
  assert.equal(canReserve({ status: 'sending', attempts: 1, sendingAt: '2026-08-26T23:58:00.000Z' }, NOW, LEASE, 3).reason, 'sending_in_progress');
  assert.equal(canReserve({ status: 'sending', attempts: 1, sendingAt: '2026-08-26T23:54:00.000Z' }, NOW, LEASE, 3).allowed, true);
});

test('通知达到最大重试次数后不会继续打扰用户', () => {
  assert.equal(canReserve({ status: 'retry_wait', attempts: 3, retryAfter: '2026-08-26T23:59:00.000Z' }, NOW, LEASE, 3).reason, 'retry_exhausted');
  assert.equal(canReserve({ status: 'sent', attempts: 1 }, NOW, LEASE, 3).reason, 'already_handled');
});
