function cleanupPhase(request, currentTime = Date.now()) {
  if (!request || typeof request !== 'object') throw new Error('删除请求格式无效。');
  if (request.status === 'pending_partner_confirmation' && Date.parse(request.expiresAt) <= currentTime) return 'expire_pending';
  if (request.status === 'scheduled' && Date.parse(request.executeAfter) <= currentTime) return 'primary';
  if (request.status === 'primary_deleted' && Date.parse(request.backupDeleteAfter) <= currentTime) return 'backup';
  return 'wait';
}

function closePendingRequestPatch(cancelledAt) {
  return {
    status: 'cancelled_space_closed',
    cancelledAt,
    unset: ['requestedBy', 'requestedByPartnerId', 'confirmedBy'],
  };
}

module.exports = { cleanupPhase, closePendingRequestPatch };
