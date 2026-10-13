import { useState } from 'react';
import { Icon } from './Icons.jsx';

function RepairStatus({ event, role }) {
  if (event.repairStatus === 'repaired') {
    return <div className="repair-state is-complete"><Icon name="check" size={18} /><span>这件事已经确认修复完成</span></div>;
  }
  if (event.repairStatus === 'repairing') {
    return <div className="repair-state"><Icon name="leaf" size={18} /><span>{role === 'wife' ? '他已经提交修复，等待你的确认' : '已经提交，等待她确认'}</span></div>;
  }
  return <div className="repair-state"><Icon name="bell" size={18} /><span>{role === 'wife' ? '已经记录，等待他认真回应' : '她希望你先看见这份感受'}</span></div>;
}

export function RepairScreen({ event, role, onBack, onSubmit, onComplete, pending = false }) {
  const [content, setContent] = useState('');
  const canSubmit = content.trim().length >= 2;

  function submit(eventObject) {
    eventObject.preventDefault();
    if (!canSubmit) return;
    onSubmit(content.trim());
  }

  if (!event) {
    return (
      <main className="page page-form">
        <header className="page-header"><button className="icon-button" onClick={onBack} type="button" aria-label="返回"><Icon name="back" /></button><h1>修复行动</h1><span className="header-spacer" /></header>
        <p className="empty-inline repair-empty">此刻没有需要修复的事情。</p>
      </main>
    );
  }

  const needsResponse = event.repairStatus === 'needs_response';
  const repairing = event.repairStatus === 'repairing';

  return (
    <main className="page page-form">
      <header className="page-header">
        <button className="icon-button" onClick={onBack} type="button" aria-label="返回"><Icon name="back" /></button>
        <h1>{role === 'wife' ? '确认修复行动' : '回应这件事'}</h1>
        <span className="header-spacer" />
      </header>

      <section className="repair-detail-card">
        <span>她记录的不舒服</span>
        <h2>{event.content}</h2>
        <strong>{event.points}</strong>
      </section>

      <RepairStatus event={event} role={role} />

      {repairing ? (
        <section className="repair-plan-card">
          <span>准备这样修复</span>
          <p>{event.repairContent}</p>
        </section>
      ) : null}

      {role === 'husband' && needsResponse ? (
        <form className="repair-form" onSubmit={submit}>
          <label htmlFor="repair-content">你准备怎么修复？</label>
          <p>写下具体行动，比只说“我错了”更容易让彼此看见改变。</p>
          <div className="textarea-wrap">
            <textarea id="repair-content" maxLength={300} onChange={(input) => setContent(input.target.value)} placeholder="例如：今晚先认真听你把感受说完，以后做决定前先问问你的想法" rows={6} value={content} />
            <span className="char-count">{content.length}/300</span>
          </div>
          {content.length > 0 && content.trim().length < 2 ? <p className="field-hint" role="status">再写一个字就可以提交了</p> : null}
          <button className="primary-button" disabled={!canSubmit || pending} type="submit">{pending ? '正在提交…' : '我收到了，提交修复'}</button>
        </form>
      ) : null}

      {role === 'wife' && repairing ? (
        <div className="repair-confirm-block">
          <p>确认后只会关闭这条修复事项，原来的扣分和记录仍会永久保留。</p>
          <button className="primary-button" disabled={pending} onClick={onComplete} type="button">{pending ? '正在确认…' : '确认修复完成'}</button>
        </div>
      ) : null}
    </main>
  );
}
