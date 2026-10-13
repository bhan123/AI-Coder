function clientRecordWithoutOtherContributions(record) {
  const { _id, response, respondedAt, respondedBy, reviewedBy, reviewedAt, confirmedBy, decidedAt, ...rest } = record;
  return { ...rest, id: _id };
}

function buildPersonalRecordExport(records, memberships) {
  const identityByCouple = new Map(memberships.map((membership) => [membership.coupleId, membership.partnerId]));
  const authoredRecords = [];
  const contributions = [];

  for (const record of records) {
    const partnerId = identityByCouple.get(record.coupleId);
    if (!partnerId) continue;
    if (record.authorId === partnerId) {
      authoredRecords.push(clientRecordWithoutOtherContributions(record));
      continue;
    }
    if (record.respondedBy === partnerId && typeof record.response === 'string') {
      contributions.push({ recordId: record._id, coupleId: record.coupleId, type: 'response', response: record.response, respondedAt: record.respondedAt || null });
    }
    if (record.reviewedBy === partnerId) {
      contributions.push({ recordId: record._id, coupleId: record.coupleId, type: 'care_review', decision: record.status, points: record.effectivePoints || null, reviewedAt: record.reviewedAt || null });
    }
    if (record.confirmedBy === partnerId) {
      contributions.push({ recordId: record._id, coupleId: record.coupleId, type: 'rule_decision', decision: record.status, decidedAt: record.decidedAt || null });
    }
  }
  return { authoredRecords, contributions };
}

module.exports = { buildPersonalRecordExport };
