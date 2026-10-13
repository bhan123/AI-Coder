import { useState } from 'react';
import { Icon, SparkMark } from './Icons.jsx';

function AccessFrame({ children }) {
  return <main className="setup-page access-page"><header className="setup-brand"><SparkMark size={36} /><strong>爱意加油站</strong></header>{children}</main>;
}

export function LoadingScreen() {
  return <AccessFrame><div className="access-centered"><span className="loading-spark">✦</span><p>正在确认这是不是属于你们的加油站</p></div></AccessFrame>;
}

export function InvitationLanding() {
  return (
    <AccessFrame>
      <section className="access-copy">
        <p>只给两个人的小地方</p>
        <h1>等一封<br />专属邀请</h1>
        <span>让对方把邀请链接发到微信。链接只用一次，进入后才会看见属于你们的账本。</span>
      </section>
      <div className="access-note"><Icon name="leaf" size={19} /><p>不搜索、不公开，也不向任何人展示你们的记录。</p></div>
    </AccessFrame>
  );
}

export function InvitationAcceptScreen({ error, onAccept, pending }) {
  const [displayName, setDisplayName] = useState('');
  const ready = displayName.trim().length > 0;

  function submit(event) {
    event.preventDefault();
    if (ready) onAccept(displayName.trim());
  }

  return (
    <AccessFrame>
      <section className="access-copy">
        <p>一封专属邀请</p>
        <h1>欢迎来到<br />你们的小地方</h1>
        <span>先留下一个你希望对方看见的称呼。这个邀请只会把你带进一个加油站。</span>
      </section>
      <form className="invite-form" onSubmit={submit}>
        <label htmlFor="display-name">你的称呼</label>
        <input autoFocus id="display-name" maxLength="24" onChange={(event) => setDisplayName(event.target.value)} placeholder="例如：小雨" value={displayName} />
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="primary-button" disabled={!ready || pending} type="submit">{pending ? '正在进入…' : '进入加油站'}</button>
      </form>
    </AccessFrame>
  );
}

export function WaitingForWifeScreen({ error, onRefresh, pending }) {
  return (
    <AccessFrame>
      <section className="access-copy waiting-copy">
        <p>第一件小事，交给她</p>
        <h1>等她设定<br />现在的温度</h1>
        <span>她选定初始值后，加油站才会正式开启。现在不用催，让她按自己的感受来。</span>
      </section>
      <div className="waiting-illustration" aria-hidden="true"><span>◌</span><i /><i /><i /></div>
      <div className="setup-footer">
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="secondary-button" disabled={pending} onClick={onRefresh} type="button">{pending ? '正在刷新…' : '刷新状态'}</button>
      </div>
    </AccessFrame>
  );
}

export function AccessErrorScreen({ message, onRetry, pending }) {
  return (
    <AccessFrame>
      <section className="access-copy">
        <p>还没有连上</p>
        <h1>暂时无法打开<br />加油站</h1>
        <span>{message}</span>
      </section>
      <div className="setup-footer"><button className="primary-button" disabled={pending} onClick={onRetry} type="button">重新尝试</button></div>
    </AccessFrame>
  );
}
