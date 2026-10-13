const assert = require('node:assert/strict');
const test = require('node:test');
const { buildTemplateData, labelFor } = require('../cloudfunctions/notification-dispatch/lib/messages');

test('订阅提醒只使用中性事件文案，不携带伴侣填写的正文', () => {
  const data = buildTemplateData('feeling_pending', '2026-08-26T10:20:00.000Z', 'thing1', 'time2');
  assert.equal(data.thing1.value, '有一份感受等待你回应');
  assert.equal(data.time2.value, '2026-08-26 18:20');
  assert.doesNotMatch(JSON.stringify(data), /晚饭|争吵|content|response/i);
});

test('未知事件类型有安全的兜底文案', () => {
  assert.equal(labelFor('unknown_event'), '共同空间有一条新动态');
});
