const FINAL_STATUSES = new Set(['sent', 'sent_unconfirmed', 'skipped_space_closed', 'skipped_no_permission', 'retry_exhausted']);

function isDue(iso, currentTime) { return !iso || Date.parse(iso) <= currentTime; }
function isSendingLeaseExpired(sendingAt, currentTime, leaseMs) {
  return typeof sendingAt !== 'string' || Date.parse(sendingAt) <= currentTime - leaseMs;
}
function canReserve(outbox, currentTime, leaseMs, maxAttempts) {
  if (!outbox || FINAL_STATUSES.has(outbox.status)) return { allowed: false, reason: 'already_handled' };
  if (outbox.status === 'retry_wait' && !isDue(outbox.retryAfter, currentTime)) return { allowed: false, reason: 'retry_not_due' };
  if (outbox.status === 'sending' && !isSendingLeaseExpired(outbox.sendingAt, currentTime, leaseMs)) return { allowed: false, reason: 'sending_in_progress' };
  if (outbox.attempts >= maxAttempts) return { allowed: false, reason: 'retry_exhausted' };
  if (outbox.status !== 'pending' && outbox.status !== 'retry_wait' && outbox.status !== 'sending') return { allowed: false, reason: 'unknown_status' };
  return { allowed: true };
}

module.exports = { FINAL_STATUSES, isSendingLeaseExpired, canReserve };
