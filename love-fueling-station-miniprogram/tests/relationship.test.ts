import assert from 'node:assert/strict';
import test from 'node:test';
import {
  createInitialRelationship,
  decideScoreAdjustment,
  pendingForViewer,
  proposeScoreAdjustment,
  respondToRecord,
  reviewCare,
  scoreStatus,
  submitCare,
  submitFeeling,
  switchViewer,
} from '../src/domain/relationship';

test('行动必须由对方通过、调整分数或驳回后才改变分数', () => {
  const initial = createInitialRelationship();
  const submitted = submitCare(initial, '今天提前准备好了晚饭，也先问了你的感受。', 1);
  const care = submitted.records[0];
  assert.equal(submitted.score, 70);
  assert.equal(pendingForViewer(switchViewer(submitted)).length, 1);

  const approved = reviewCare(switchViewer(submitted), care.id, true, 5);
  assert.equal(approved.score, 75);
  assert.equal(approved.records[0].kind === 'care' && approved.records[0].effectivePoints, 5);
  assert.throws(() => reviewCare(approved, care.id, true, 3), /已经审批/);

  const another = submitCare(initial, '认真收拾好了家里。', 3);
  const rejected = reviewCare(switchViewer(another), another.records[0]?.id || '', false, 3);
  assert.equal(rejected.score, 70);
});

test('感受记录立即扣分，仍可以由对方认真回应', () => {
  const initial = createInitialRelationship();
  const withFeeling = submitFeeling(initial, '刚才我感到自己的想法没有被听见。', -5);
  const feeling = withFeeling.records[0];
  assert.equal(withFeeling.score, 65);
  assert.equal(feeling.kind === 'feeling' && feeling.effectivePoints, -5);
  const responded = respondToRecord(switchViewer(withFeeling), feeling.id, '我听见了，今晚先认真听你说完。');
  assert.equal(responded.records[0].kind === 'feeling' && responded.records[0].status, 'responded');
});

test('后续手动调分必须由另一方确认，且有默认分段提醒', () => {
  const initial = createInitialRelationship();
  const proposed = proposeScoreAdjustment(initial, 90, '这段时间彼此都在认真投入，想把当前分数调回90。');
  const adjustment = proposed.records[0];
  assert.equal(proposed.score, 70);
  assert.throws(() => decideScoreAdjustment(proposed, adjustment.id, true), /需要由对方确认/);
  const confirmed = decideScoreAdjustment(switchViewer(proposed), adjustment.id, true);
  assert.equal(confirmed.score, 90);
  assert.equal(scoreStatus(90).title, '爱意炽烈');
  assert.equal(scoreStatus(15).alert, true);
});

test('本地体验模式中的感受回应也不能覆盖第一次回应', () => {
  const withFeeling = submitFeeling(createInitialRelationship(), '我希望你先听见我的感受');
  const feeling = withFeeling.records[0];
  const once = respondToRecord(switchViewer(withFeeling), feeling.id, '我认真听见了');
  assert.throws(() => respondToRecord(once, feeling.id, '覆盖第一次回应'), /已回应/);
});
