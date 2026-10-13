function personalRecordScrubPlan(record, partnerId) {
  if (record.authorId === partnerId) return { action: 'delete' };
  const set = {};
  const unset = [];
  if (record.respondedBy === partnerId) {
    unset.push('response', 'respondedAt', 'respondedBy');
    set.status = 'awaiting_response';
  }
  if (record.reviewedBy === partnerId) {
    unset.push('reviewedBy', 'reviewedAt', 'effectivePoints');
    set.status = 'pending';
  }
  if (record.confirmedBy === partnerId) {
    unset.push('confirmedBy', 'decidedAt');
    set.status = 'pending';
  }
  return { action: 'update', set, unset };
}

function personalReferenceScrubPlan(document, userId) {
  const set = {};
  const unset = [];
  if (Array.isArray(document.memberIds) && document.memberIds.includes(userId)) set.memberIds = document.memberIds.filter((id) => id !== userId);
  if (document.acceptedBy === userId) {
    unset.push('acceptedBy', 'acceptedAt');
    set.status = 'accepted_user_deleted';
  }
  if (document.requestedBy === userId) {
    unset.push('requestedBy', 'requestedByPartnerId');
    if (document.status === 'pending_partner_confirmation') {
      set.status = 'cancelled_by_personal_deletion';
      set.cancelledAt = new Date().toISOString();
    }
  }
  if (document.confirmedBy === userId) unset.push('confirmedBy');
  if (document.closedBy === userId) unset.push('closedBy');
  return { action: 'update', set, unset };
}

module.exports = { personalRecordScrubPlan, personalReferenceScrubPlan };
