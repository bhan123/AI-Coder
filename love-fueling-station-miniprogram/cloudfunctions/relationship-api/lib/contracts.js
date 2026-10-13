function toClientRecord(document) {
  if (!document || typeof document !== 'object' || typeof document._id !== 'string') {
    throw new Error('云端记录缺少数据库 ID。');
  }
  const { _id, ...record } = document;
  return { ...record, id: _id };
}

function assertPairingAvailable({ invite, creatorLock, accepterLock, currentTime }) {
  if (!invite || invite.status !== 'active' || Date.parse(invite.expiresAt) <= currentTime) {
    throw new Error('邀请码已失效，请重新获取。');
  }
  if (invite.creatorUserId === accepterLock.userId) throw new Error('不能接受自己创建的邀请码。');
  if (creatorLock.activeCoupleId) throw new Error('邀请创建者已经加入其他共同空间。');
  if (accepterLock.activeCoupleId) throw new Error('你已经在一个共同空间中。');
}

function responsePatch(record, viewerId, response, respondedAt) {
  if (!record || record.kind !== 'feeling' || record.authorId === viewerId) throw new Error('你不能回应这条感受。');
  if (record.status !== 'awaiting_response') throw new Error('这条记录已经回应过，不能覆盖原回应。');
  return {
    status: 'responded',
    response,
    respondedAt,
    respondedBy: viewerId,
  };
}

function careReviewPatch(record, viewerId, decision, effectivePoints, reviewedAt) {
  if (!record || record.kind !== 'care' || record.authorId === viewerId) throw new Error('你不能审批这条行动。');
  if (record.status !== 'pending') throw new Error('这条行动已经处理，不能重复审批。');
  if (decision !== 'approved' && decision !== 'rejected') throw new Error('请给出通过或驳回的决定。');
  return {
    status: decision,
    reviewedBy: viewerId,
    reviewedAt,
    ...(decision === 'approved' ? { effectivePoints } : {}),
  };
}

function ruleDecisionPatch(record, viewerId, accept, decidedAt) {
  if (!record || record.kind !== 'rule' || record.authorId === viewerId) throw new Error('这条约定暂时无法由你处理。');
  if (record.status !== 'pending') throw new Error('这条约定已经处理，不能重复确认或改写结果。');
  return { status: accept ? 'confirmed' : 'declined', confirmedBy: viewerId, decidedAt };
}

module.exports = { assertPairingAvailable, responsePatch, careReviewPatch, ruleDecisionPatch, toClientRecord };
