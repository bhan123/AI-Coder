import { useState } from 'react';
import { Icon } from './Icons.jsx';

const levels = [
  { points: 1, label: '小小用心', symbol: 'leaf' },
  { points: 3, label: '认真行动', symbol: 'heart' },
  { points: 5, label: '特别用心', symbol: 'star' },
];

export function ActionForm({ onBack, onSubmit, pending = false }) {
  const [content, setContent] = useState('');
  const [points, setPoints] = useState(3);
  const canSubmit = content.trim().length >= 2;

  function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit({ content: content.trim(), points });
  }

  return (
    <main className="page page-form">
      <header className="page-header">
        <button className="icon-button" onClick={onBack} type="button" aria-label="返回">
          <Icon name="back" />
        </button>
        <h1>记录爱的行动</h1>
        <span className="header-spacer" />
      </header>

      <form className="action-form" onSubmit={handleSubmit}>
        <label className="sr-only" htmlFor="action-content">今天为她做了什么？</label>
        <div className="textarea-wrap">
          <textarea
            autoFocus
            id="action-content"
            maxLength={300}
            onChange={(event) => setContent(event.target.value)}
            placeholder="今天为她做了什么？"
            rows={7}
            value={content}
          />
          <span className="char-count">{content.length}/300</span>
        </div>
        {content.length > 0 && content.trim().length < 2 ? <p className="field-hint" role="status">再写一个字就可以提交了</p> : null}

        <fieldset className="point-fieldset">
          <legend>选择本次用心程度</legend>
          <div className="point-grid">
            {levels.map((level) => (
              <button
                aria-pressed={points === level.points}
                className={`point-option ${points === level.points ? 'is-selected' : ''}`}
                key={level.points}
                onClick={() => setPoints(level.points)}
                type="button"
              >
                <span className={`point-symbol point-symbol-${level.symbol}`} aria-hidden="true">
                  {level.symbol === 'leaf' ? '♧' : level.symbol === 'heart' ? '♡' : '☆'}
                </span>
                <span>{level.label}</span>
                <strong>+{level.points}</strong>
              </button>
            ))}
          </div>
        </fieldset>

        <p className="form-note"><Icon name="leaf" size={17} />记录行动，不是证明自己</p>

        <button className="primary-button submit-button" disabled={!canSubmit || pending} type="submit">
          {pending ? '正在提交…' : '提交给她'}
        </button>
      </form>
    </main>
  );
}
