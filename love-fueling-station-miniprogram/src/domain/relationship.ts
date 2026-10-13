export type PartnerId = 'partner-a' | 'partner-b';
export type PositivePoints = 1 | 3 | 5;
export type NegativePoints = -1 | -3 | -5;
export type RecordAttachment = { fileId: string };

export type CareRecord = {
  id: string; kind: 'care'; authorId: PartnerId; content: string; createdAt: string;
  status: 'pending' | 'approved' | 'rejected'; requestedPoints: PositivePoints;
  effectivePoints?: PositivePoints; reviewedBy?: PartnerId; reviewedAt?: string; attachments?: RecordAttachment[];
};
export type FeelingRecord = {
  id: string; kind: 'feeling'; authorId: PartnerId; content: string; createdAt: string;
  status: 'awaiting_response' | 'responded'; effectivePoints: NegativePoints;
  response?: string; respondedAt?: string; attachments?: RecordAttachment[];
};
export type RuleProposal = {
  id: string; kind: 'rule'; authorId: PartnerId; title: string; content: string; createdAt: string;
  status: 'pending' | 'confirmed' | 'declined'; confirmedBy?: PartnerId;
};
export type ScoreAdjustment = {
  id: string; kind: 'score_adjustment'; authorId: PartnerId; content: string; createdAt: string;
  status: 'pending' | 'confirmed' | 'declined'; proposedScore: number; confirmedBy?: PartnerId;
};
export type RelationshipRecord = CareRecord | FeelingRecord | RuleProposal | ScoreAdjustment;
export type RelationshipState = { schemaVersion: 2; viewerId: PartnerId; score: number; records: RelationshipRecord[] };

export const partnerName = (partnerId: PartnerId, viewerId: PartnerId) => partnerId === viewerId ? '我' : '对方';
export const otherPartner = (partnerId: PartnerId): PartnerId => partnerId === 'partner-a' ? 'partner-b' : 'partner-a';

export function createInitialRelationship(): RelationshipState {
  return {
    schemaVersion: 2, viewerId: 'partner-a', score: 70,
    records: [{
      id: 'welcome-care', kind: 'care', authorId: 'partner-b', content: '愿意一起把感受说清楚，也把行动慢慢做好。', createdAt: new Date().toISOString(),
      status: 'approved', requestedPoints: 3, effectivePoints: 3, reviewedBy: 'partner-a', reviewedAt: new Date().toISOString(),
    }],
  };
}

export function validateRecordContent(value: string) {
  const content = value.trim();
  if (content.length < 2) throw new Error('请至少写下两个字。');
  if (content.length > 300) throw new Error('内容请控制在300字以内。');
  return content;
}
export function validateScore(value: number) {
  if (!Number.isInteger(value) || value < 0 || value > 100) throw new Error('分数需在0到100之间。');
  return value;
}
export function validatePositivePoints(value: number): PositivePoints {
  if (value === 1 || value === 3 || value === 5) return value;
  throw new Error('行动加分只能是+1、+3或+5。');
}
export function validateNegativePoints(value: number): NegativePoints {
  if (value === -1 || value === -3 || value === -5) return value;
  throw new Error('感受扣分只能是-1、-3或-5。');
}
function nextId(prefix: string) { return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
function changeScore(score: number, points: number) { return Math.max(0, Math.min(100, score + points)); }

export function submitCare(state: RelationshipState, content: string, requestedPoints: PositivePoints = 3): RelationshipState {
  const record: CareRecord = { id: nextId('care'), kind: 'care', authorId: state.viewerId, content: validateRecordContent(content), createdAt: new Date().toISOString(), status: 'pending', requestedPoints: validatePositivePoints(requestedPoints) };
  return { ...state, records: [record, ...state.records] };
}
export function reviewCare(state: RelationshipState, recordId: string, accept: boolean, effectivePoints: PositivePoints = 3): RelationshipState {
  const record = state.records.find((item) => item.id === recordId);
  if (!record || record.kind !== 'care' || record.authorId === state.viewerId) throw new Error('这条行动暂时无法由你处理。');
  if (record.status !== 'pending') throw new Error('这条行动已经审批过，不能重复处理。');
  const points = validatePositivePoints(effectivePoints);
  const reviewed: CareRecord = { ...record, status: accept ? 'approved' : 'rejected', reviewedBy: state.viewerId, reviewedAt: new Date().toISOString(), ...(accept ? { effectivePoints: points } : {}) };
  return { ...state, score: accept ? changeScore(state.score, points) : state.score, records: state.records.map((item) => item.id === recordId ? reviewed : item) };
}
export function submitFeeling(state: RelationshipState, content: string, points: NegativePoints = -3): RelationshipState {
  const effectivePoints = validateNegativePoints(points);
  const record: FeelingRecord = { id: nextId('feeling'), kind: 'feeling', authorId: state.viewerId, content: validateRecordContent(content), createdAt: new Date().toISOString(), status: 'awaiting_response', effectivePoints };
  return { ...state, score: changeScore(state.score, effectivePoints), records: [record, ...state.records] };
}
export function respondToRecord(state: RelationshipState, recordId: string, response: string): RelationshipState {
  const normalizedResponse = validateRecordContent(response);
  const record = state.records.find((item) => item.id === recordId);
  if (!record || record.kind !== 'feeling' || record.authorId === state.viewerId) throw new Error('这条感受暂时无法由你回应。');
  if (record.status !== 'awaiting_response') throw new Error('这条感受已回应，不能覆盖第一次回应。');
  return { ...state, records: state.records.map((item) => item.id === recordId && item.kind === 'feeling' ? { ...item, status: 'responded', response: normalizedResponse, respondedAt: new Date().toISOString() } : item) };
}
export function proposeRule(state: RelationshipState, payload: { title: string; content: string }): RelationshipState {
  const record: RuleProposal = { id: nextId('rule'), kind: 'rule', authorId: state.viewerId, title: validateRecordContent(payload.title), content: validateRecordContent(payload.content), createdAt: new Date().toISOString(), status: 'pending' };
  return { ...state, records: [record, ...state.records] };
}
export function confirmRule(state: RelationshipState, recordId: string, accept: boolean): RelationshipState {
  const rule = state.records.find((item) => item.id === recordId);
  if (!rule || rule.kind !== 'rule' || rule.status !== 'pending' || rule.authorId === state.viewerId) throw new Error('这条共同约定已处理，或需要由对方确认。');
  const confirmed: RuleProposal = { ...rule, status: accept ? 'confirmed' : 'declined', confirmedBy: state.viewerId };
  return { ...state, records: state.records.map((item) => item.id === recordId ? confirmed : item) };
}
export function proposeScoreAdjustment(state: RelationshipState, score: number, reason: string): RelationshipState {
  const record: ScoreAdjustment = { id: nextId('score'), kind: 'score_adjustment', authorId: state.viewerId, content: validateRecordContent(reason), proposedScore: validateScore(score), createdAt: new Date().toISOString(), status: 'pending' };
  return { ...state, records: [record, ...state.records] };
}
export function decideScoreAdjustment(state: RelationshipState, recordId: string, accept: boolean): RelationshipState {
  const record = state.records.find((item) => item.id === recordId);
  if (!record || record.kind !== 'score_adjustment' || record.status !== 'pending' || record.authorId === state.viewerId) throw new Error('这条调分申请已处理，或需要由对方确认。');
  const decided: ScoreAdjustment = { ...record, status: accept ? 'confirmed' : 'declined', confirmedBy: state.viewerId };
  return { ...state, score: accept ? record.proposedScore : state.score, records: state.records.map((item) => item.id === recordId ? decided : item) };
}
export function switchViewer(state: RelationshipState): RelationshipState { return { ...state, viewerId: otherPartner(state.viewerId) }; }
export function pendingForViewer(state: RelationshipState) {
  return state.records.filter((record) => {
    if (record.authorId === state.viewerId) return false;
    return record.kind === 'care' || record.kind === 'rule' || record.kind === 'score_adjustment' ? record.status === 'pending' : record.status === 'awaiting_response';
  });
}
export function scoreStatus(score: number) {
  if (score >= 90) return { title: '爱意炽烈', description: '你们的努力正在被彼此看见。' };
  if (score >= 75) return { title: '甜蜜在线', description: '保持这份用心，也别忘了认真回应。' };
  if (score >= 60) return { title: '温柔待机', description: '关系需要一点主动的关心和具体行动。' };
  if (score >= 40) return { title: '需要充电', description: '可以先做一件小而确定的事，让彼此感到被在乎。' };
  if (score >= 20) return { title: '修复时刻', description: '先把感受听完，再讨论怎样修复。' };
  return { title: '暂停计分', description: '分数已进入关怀提醒区间：先停止争论加减分，回到安全、倾听和具体沟通。', alert: true };
}
