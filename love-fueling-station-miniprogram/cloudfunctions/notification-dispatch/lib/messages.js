const labels = {
  care_pending: '有一件行动等待你查看',
  feeling_pending: '有一份感受等待你回应',
  care_approved: '你提交的行动已被通过',
  care_rejected: '一件行动需要再沟通',
  feeling_responded: '对方认真回应了一份感受',
  rule_pending: '有一条共同约定等待确认',
  rule_confirmed: '一条共同约定已确认',
  rule_declined: '一条共同约定暂不启用',
  score_adjustment_pending: '有一项调分申请等待确认',
  score_adjustment_confirmed: '一项调分申请已确认',
  score_adjustment_declined: '一项调分申请未通过',
};

function labelFor(type) { return labels[type] || '共同空间有一条新动态'; }
function formatNotificationTime(iso) {
  const date = new Date(iso);
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
function buildTemplateData(type, createdAt, eventField, timeField) {
  return {
    [eventField]: { value: labelFor(type).slice(0, 20) },
    [timeField]: { value: formatNotificationTime(createdAt) },
  };
}

module.exports = { labelFor, buildTemplateData };
