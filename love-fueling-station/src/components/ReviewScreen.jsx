import { useState } from 'react';
import { Icon } from './Icons.jsx';

const deductionLevels = [
  { points: -1, label: '小疏忽', symbol: '♧' },
  { points: -3, label: '让我不舒服', symbol: '☹' },
  { points: -5, label: '需要认真修复', symbol: '♡' },
];

export function ReviewScreen({ pendingActions, onBack, onResolve, onDeduct, pending = false }) {
  const [adjustingId, setAdjustingId] = useState(null);
  const [deduction, setDeduction] = useState(-3);
  const [reason, setReason] = useState('');
  const firstPending = pendingActions[0];

  function submitDeduction(event) {
    event.preventDefault();
    if (reason.trim().length < 2) return;
    onDeduct({ points: deduction, content: reason.trim() });
    setReason('');
  }

  return (
    <main className="page review-page">
      <header className="page-header">
        <button className="icon-button" onClick={onBack} type="button" aria-label="返回">
          <Icon name="back" />
        </button>
        <h1>等待你的回应</h1>
        <span className="header-spacer" />
      </header>

      {firstPending ? (
        <section className="review-panel" aria-labelledby="review-action-title">
          <div className="review-meta">
            <span className="round-icon"><Icon name="book" size={19} /></span>
            <div><strong id="review-action-title">他提交的行动</strong><small>刚刚</small></div>
          </div>
          <div className="review-content">
            <h2>{firstPending.content}</h2>
            {firstPending.hasPhoto ? <img className="review-photo" src={`/api/v1/events/${encodeURIComponent(firstPending.id)}/photo`} alt="他提交的行动照片" /> : null}
            <span>申请获得</span>
            <strong className="requested-points">+{firstPending.points}</strong>
          </div>
          {adjustingId === firstPending.id ? (
            <div className="adjust-row" aria-label="调整分值">
              {[1, 3, 5].map((points) => (
                <button disabled={pending} key={points} onClick={() => onResolve(firstPending.id, 'approved', points)} type="button">+{points}</button>
              ))}
              <button className="adjust-cancel" disabled={pending} onClick={() => setAdjustingId(null)} type="button">取消</button>
            </div>
          ) : (
            <div className="review-actions">
              <button className="approve-button" disabled={pending} onClick={() => onResolve(firstPending.id, 'approved', firstPending.points)} type="button"><Icon name="check" size={19} />通过</button>
              <button className="adjust-button" disabled={pending} onClick={() => setAdjustingId(firstPending.id)} type="button"><Icon name="adjust" size={18} />调整</button>
              <button className="reject-button" disabled={pending} onClick={() => onResolve(firstPending.id, 'rejected')} type="button"><Icon name="close" size={18} />驳回</button>
            </div>
          )}
        </section>
      ) : (
        <section className="empty-review">
          <span className="empty-spark">✦</span>
          <h2>没有等待确认的行动</h2>
          <p>今天可以轻松一点，或者主动记录一件他的好。</p>
        </section>
      )}

      <form className="deduction-panel" onSubmit={submitDeduction}>
        <div className="review-meta">
          <span className="round-icon sad-icon">﹏</span>
          <div><strong>记录一次不舒服</strong><small>如果有需要被看见的感受</small></div>
        </div>
        <label htmlFor="deduction-reason">发生了什么？</label>
        <textarea
          id="deduction-reason"
          maxLength={180}
          onChange={(event) => setReason(event.target.value)}
          placeholder="简单写下事情和你的感受"
          rows={3}
          value={reason}
        />
        <fieldset>
          <legend>选择影响程度</legend>
          <div className="deduction-grid">
            {deductionLevels.map((level) => (
              <button
                aria-pressed={deduction === level.points}
                className={deduction === level.points ? 'is-selected' : ''}
                key={level.points}
                onClick={() => setDeduction(level.points)}
                type="button"
              >
                <span aria-hidden="true">{level.symbol}</span>
                <small>{level.label}</small>
                <strong>{level.points}</strong>
              </button>
            ))}
          </div>
        </fieldset>
        <button className="primary-button" disabled={reason.trim().length < 2 || pending} type="submit">{pending ? '正在记录…' : '直接记录'}</button>
      </form>
    </main>
  );
}
