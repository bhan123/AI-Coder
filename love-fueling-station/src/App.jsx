import { useCallback, useEffect, useMemo, useState } from 'react';
import { AccessErrorScreen, InvitationAcceptScreen, InvitationLanding, LoadingScreen, WaitingForWifeScreen } from './components/AccessScreens.jsx';
import { ActionForm } from './components/ActionForm.jsx';
import { BottomNav } from './components/BottomNav.jsx';
import { Icon, SparkMark } from './components/Icons.jsx';
import { ReviewScreen } from './components/ReviewScreen.jsx';
import { RepairScreen } from './components/RepairScreen.jsx';
import { ScoreGauge } from './components/ScoreGauge.jsx';
import { stationApi } from './api/station.js';

const initialState = {
  isInitialized: false,
  initialScore: null,
  score: null,
  mileage: 0,
  actions: [],
};

const ledgerRanges = [
  { id: 'month', label: '近1月', days: 30 },
  { id: 'quarter', label: '近3月', days: 90 },
  { id: 'all', label: '全部', days: null },
];

function getScoreStatus(score) {
  if (score >= 90) return '爱意炽烈';
  if (score >= 75) return '甜蜜在线';
  if (score >= 60) return '温柔待机';
  if (score >= 40) return '需要充电';
  if (score >= 20) return '修复时刻';
  return '暂停计分';
}

function InitialSetupScreen({ error, isSaving, onConfirm }) {
  const [score, setScore] = useState(70);
  const status = getScoreStatus(score);

  function updateScore(value) {
    const nextScore = Number(value);
    if (Number.isFinite(nextScore)) setScore(Math.max(0, Math.min(100, nextScore)));
  }

  return (
    <main className="setup-page">
      <header className="setup-brand"><SparkMark size={36} /><strong>爱意加油站</strong></header>
      <section className="setup-copy">
        <p>第一件小事，交给她</p>
        <h1>由她来设定<br />现在的初始温度</h1>
        <span>这不是对谁的判决，只是此刻她心里对这段关系的温度。</span>
      </section>

      <section className="initial-score-picker" aria-labelledby="initial-score-heading">
        <h2 id="initial-score-heading">她选择的起始值</h2>
        <div className="initial-score-output">
          <input
            aria-label="直接输入初始温度"
            max="100"
            min="0"
            onChange={(event) => updateScore(event.target.value)}
            type="number"
            value={score}
          />
          <span>{status}</span>
        </div>
        <input
          aria-label="爱意温度初始值"
          id="initial-score"
          max="100"
          min="0"
          onChange={(event) => updateScore(event.target.value)}
          style={{ '--range-progress': `${score}%` }}
          type="range"
          value={score}
        />
        <div className="range-labels" aria-hidden="true"><span>0</span><span>50</span><span>100</span></div>
        <p>以后，分数会由最近30天的行动与修复慢慢变化。</p>
      </section>

      <div className="setup-footer">
        <p><Icon name="leaf" size={16} />只有她确认后，才会正式开启</p>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="primary-button" disabled={isSaving} onClick={() => onConfirm(score)} type="button">{isSaving ? '正在开启…' : `以 ${score} 分开启加油站`}</button>
      </div>
    </main>
  );
}

function HomeScreen({ role, state, pendingCount, repair, onNavigate }) {
  return (
    <main className="page home-page">
      <header className="brand-header">
        <div className="brand"><SparkMark /><strong>爱意加油站</strong></div>
        <button className="quiet-link" onClick={() => onNavigate('us')} type="button">仅我们可见</button>
      </header>

      <section className="home-intro">
        <h1>{role === 'wife' ? '早上好，今天也认真爱彼此' : '早上好，今天也认真爱她'}</h1>
      </section>

      <ScoreGauge score={state.score} status={getScoreStatus(state.score)} />

      <button className="primary-button record-button" onClick={() => onNavigate(role === 'wife' ? 'review' : 'submit')} type="button">
        <Icon name={role === 'wife' ? 'book' : 'pencil'} size={21} />{role === 'wife' ? '查看他的行动' : '记录爱的行动'}
      </button>

      <button className="pending-row" onClick={() => onNavigate(role === 'wife' ? 'review' : 'ledger')} type="button">
        <Icon name="bell" size={21} />
        <span>{pendingCount > 0 ? role === 'wife' ? `有 ${pendingCount} 件加分行动等待你确认` : `有 ${pendingCount} 件加分行动等待她确认` : '暂时没有待审批的加分行动'}</span>
        <Icon name="chevron" size={18} />
      </button>

      <section className="repair-section">
        <h2>当前修复行动</h2>
        {repair ? (
          <button className="repair-row" onClick={() => onNavigate('repair')} type="button">
            <span className="repair-icon"><Icon name="wrench" size={21} /></span>
            <span>
              <strong>{repair.repairStatus === 'repairing' ? repair.repairContent : repair.content}</strong>
              <small>{repair.repairStatus === 'repairing' ? role === 'wife' ? '他已提交，等待你确认' : '已提交，等待她确认' : role === 'wife' ? '已记录，等待他回应' : '有一件事情需要你回应'}</small>
            </span>
            <Icon name="chevron" size={18} />
          </button>
        ) : <p className="empty-inline">此刻没有需要修复的事情。</p>}
      </section>
    </main>
  );
}

function formatEventTime(isoTime) {
  const date = new Date(isoTime);
  if (Number.isNaN(date.getTime())) return isoTime;
  return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date);
}

function LedgerScreen({ actions }) {
  const [range, setRange] = useState('month');
  const [referenceTime, setReferenceTime] = useState(() => Date.now());
  const visibleActions = useMemo(() => {
    const selected = ledgerRanges.find((item) => item.id === range);
    if (!selected?.days) return actions;
    const cutoff = referenceTime - selected.days * 24 * 60 * 60 * 1000;
    return actions.filter((action) => new Date(action.createdAt).getTime() >= cutoff);
  }, [actions, range, referenceTime]);

  return (
    <main className="page ledger-page">
      <header className="simple-header"><h1>爱的账本</h1><p>每一笔都保留，但不让过去一直追着我们。</p></header>
      <div aria-label="账本展示范围" className="ledger-filter" role="group">
        {ledgerRanges.map((item) => (
          <button aria-pressed={range === item.id} className={range === item.id ? 'is-selected' : ''} key={item.id} onClick={() => { setRange(item.id); setReferenceTime(Date.now()); }} type="button">{item.label}</button>
        ))}
      </div>
      <p className="history-note">记录永久保留；当前仅展示{ledgerRanges.find((item) => item.id === range)?.label}。</p>
      <div className="timeline">
        {visibleActions.map((action) => (
          <article className="timeline-item" key={action.id}>
            <span className={`timeline-dot type-${action.type}`} />
            <div>
              <time>{formatEventTime(action.createdAt)}</time>
              <h2>{action.content}</h2>
              {action.hasPhoto ? <img className="timeline-photo" loading="lazy" src={`/api/v1/events/${encodeURIComponent(action.id)}/photo`} alt="行动照片" /> : null}
              <p>{action.status === 'pending' ? '等待确认' : action.status === 'approved' ? '她已确认' : action.status === 'rejected' ? '未通过，不计分' : action.repairStatus === 'repaired' ? '感受已记录 · 修复已完成' : action.repairStatus === 'repairing' ? '感受已记录 · 等待确认修复' : '感受已记录 · 等待回应'}</p>
              {action.repairContent ? <div className="ledger-repair"><span>修复行动</span><strong>{action.repairContent}</strong></div> : null}
            </div>
            <strong className={action.points < 0 ? 'negative-points' : ''}>{action.points > 0 ? `+${action.points}` : action.points || '—'}</strong>
          </article>
        ))}
        {visibleActions.length === 0 ? <p className="empty-inline ledger-empty">这段时间还没有记录。</p> : null}
      </div>
    </main>
  );
}

function UsScreen({ initialScore, mileage, role, onReview }) {
  return (
    <main className="page us-page">
      <header className="simple-header"><h1>只属于我们</h1><p>积分记录行动，不衡量谁值不值得被爱。</p></header>
      <section className="mileage-block"><span>爱的里程</span><strong>{mileage}</strong><p>次被认真看见的行动</p></section>
      <p className="baseline-note">起始温度 <strong>{initialScore}</strong> 分，由她在初始化时设定</p>
      <section className="rules-block">
        <h2>我们的约定</h2>
        <ol>
          <li><span>01</span><p><strong>她可以直接记录不舒服</strong>你不能撤销，但可以提交修复行动。</p></li>
          <li><span>02</span><p><strong>积分不兑换原谅</strong>它只提醒我们把心意落在行动里。</p></li>
          <li><span>03</span><p><strong>低分时先暂停游戏感</strong>优先沟通、倾听和解决真正的问题。</p></li>
        </ol>
      </section>
      {role === 'wife' ? <button className="secondary-button" onClick={onReview} type="button">进入她的回应页面</button> : null}
    </main>
  );
}

function Toast({ message }) {
  return message ? <div className="toast" role="status"><span>✦</span>{message}</div> : null;
}

export default function App() {
  const [state, setState] = useState(initialState);
  const [screen, setScreen] = useState('home');
  const [toast, setToast] = useState('');
  const [access, setAccess] = useState({ status: 'loading', member: null, station: null, error: '' });
  const [accessPending, setAccessPending] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const inviteToken = useMemo(() => new URLSearchParams(window.location.search).get('invite'), []);
  const pendingActions = useMemo(() => state.actions.filter((action) => action.status === 'pending'), [state.actions]);
  const activeRepair = useMemo(() => {
    const repairs = state.actions.filter((action) => action.type === 'negative' && action.repairStatus !== 'repaired');
    if (access.member?.role === 'wife') return repairs.find((action) => action.repairStatus === 'repairing') ?? repairs[0] ?? null;
    return repairs.find((action) => action.repairStatus === 'needs_response') ?? repairs[0] ?? null;
  }, [access.member?.role, state.actions]);

  useEffect(() => {
    if (!toast) return undefined;
    const timer = window.setTimeout(() => setToast(''), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  function navigate(nextScreen) {
    setScreen(nextScreen);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const applyStation = useCallback((station, events) => {
    setState((current) => ({
      ...current,
      isInitialized: station.initialScore !== null,
      initialScore: station.initialScore,
      score: station.currentScore,
      mileage: events ? events.filter((event) => event.status === 'approved').length : current.mileage,
      actions: events ?? current.actions,
    }));
  }, []);

  const refreshAccess = useCallback(async () => {
    setAccessPending(true);
    try {
      const [payload, eventPayload] = await Promise.all([stationApi.getStation(), stationApi.getEvents()]);
      applyStation(payload.station, eventPayload.events);
      setAccess({ status: 'ready', member: payload.member, station: payload.station, error: '' });
    } catch (error) {
      if (error.status === 401) setAccess({ status: 'anonymous', member: null, station: null, error: '' });
      else setAccess({ status: 'error', member: null, station: null, error: error.message });
    } finally {
      setAccessPending(false);
    }
  }, [applyStation]);

  const resumeInviteSession = useCallback(async () => {
    setAccessPending(true);
    try {
      const [payload, eventPayload] = await Promise.all([stationApi.getStation(), stationApi.getEvents()]);
      window.history.replaceState({}, '', window.location.pathname);
      applyStation(payload.station, eventPayload.events);
      setAccess({ status: 'ready', member: payload.member, station: payload.station, error: '' });
    } catch (error) {
      if (error.status === 401) setAccess({ status: 'invitation', member: null, station: null, error: '' });
      else setAccess({ status: 'error', member: null, station: null, error: error.message });
    } finally {
      setAccessPending(false);
    }
  }, [applyStation]);

  useEffect(() => {
    if (inviteToken) {
      resumeInviteSession();
      return;
    }
    refreshAccess();
  }, [inviteToken, refreshAccess, resumeInviteSession]);

  async function acceptInvitation(displayName) {
    setAccessPending(true);
    setAccess((current) => ({ ...current, error: '' }));
    try {
      const payload = await stationApi.acceptInvitation(inviteToken, displayName);
      const eventPayload = await stationApi.getEvents();
      window.history.replaceState({}, '', window.location.pathname);
      applyStation(payload.station, eventPayload.events);
      setAccess({ status: 'ready', member: payload.member, station: payload.station, error: '' });
    } catch (error) {
      setAccess((current) => ({ ...current, error: error.message }));
    } finally {
      setAccessPending(false);
    }
  }

  async function initializeStation(initialScore) {
    setAccessPending(true);
    setAccess((current) => ({ ...current, error: '' }));
    try {
      const payload = await stationApi.initialize(initialScore);
      applyStation(payload.station);
      setAccess((current) => ({ ...current, station: payload.station }));
      setToast(`已由她设定为 ${initialScore} 分，慢慢来就好`);
    } catch (error) {
      setAccess((current) => ({ ...current, error: error.message }));
    } finally {
      setAccessPending(false);
    }
  }

  async function submitAction({ content, points, photoDataUrl }) {
    setActionPending(true);
    try {
      const payload = await stationApi.submitPositive(content, points, photoDataUrl);
      setState((current) => ({ ...current, actions: [payload.event, ...current.actions] }));
      setToast('已经提交，等待她看见');
      navigate('home');
    } catch (error) {
      setToast(error.message);
    } finally {
      setActionPending(false);
    }
  }

  async function resolveAction(id, status, adjustedPoints) {
    setActionPending(true);
    try {
      const payload = await stationApi.reviewPositive(id, status, adjustedPoints);
      setState((current) => ({
        ...current,
        score: payload.station.currentScore,
        mileage: status === 'approved' ? current.mileage + 1 : current.mileage,
        actions: current.actions.map((action) => action.id === id ? payload.event : action),
      }));
      setToast(status === 'approved' ? '已确认，这份用心被看见了' : '已驳回，本次不计分');
    } catch (error) {
      setToast(error.message);
    } finally {
      setActionPending(false);
    }
  }

  async function addDeduction({ content, points }) {
    setActionPending(true);
    try {
      const payload = await stationApi.recordNegative(content, points);
      setState((current) => ({
        ...current,
        score: payload.station.currentScore,
        actions: [payload.event, ...current.actions],
      }));
      setToast('这份感受已经被记录');
    } catch (error) {
      setToast(error.message);
    } finally {
      setActionPending(false);
    }
  }

  async function submitRepair(content) {
    if (!activeRepair) return;
    setActionPending(true);
    try {
      const payload = await stationApi.submitRepair(activeRepair.id, content);
      setState((current) => ({ ...current, actions: current.actions.map((action) => action.id === activeRepair.id ? payload.event : action) }));
      setToast('修复行动已经提交，等待她确认');
      navigate('home');
    } catch (error) {
      setToast(error.message);
    } finally {
      setActionPending(false);
    }
  }

  async function completeRepair() {
    if (!activeRepair) return;
    setActionPending(true);
    try {
      const payload = await stationApi.completeRepair(activeRepair.id);
      setState((current) => ({ ...current, actions: current.actions.map((action) => action.id === activeRepair.id ? payload.event : action) }));
      setToast('已确认修复完成，原记录会继续保留');
      navigate('home');
    } catch (error) {
      setToast(error.message);
    } finally {
      setActionPending(false);
    }
  }

  const navScreen = ['home', 'ledger', 'us'].includes(screen) ? screen : 'home';

  if (access.status === 'loading') return <div className="app-stage"><div className="app-shell"><LoadingScreen /></div></div>;
  if (access.status === 'invitation') return <div className="app-stage"><div className="app-shell"><InvitationAcceptScreen error={access.error} onAccept={acceptInvitation} pending={accessPending} /></div></div>;
  if (access.status === 'anonymous') return <div className="app-stage"><div className="app-shell"><InvitationLanding /></div></div>;
  if (access.status === 'error') return <div className="app-stage"><div className="app-shell"><AccessErrorScreen message={access.error} onRetry={refreshAccess} pending={accessPending} /></div></div>;
  if (access.station.initialScore === null && access.member.role !== 'wife') {
    return <div className="app-stage"><div className="app-shell"><WaitingForWifeScreen error={access.error} onRefresh={refreshAccess} pending={accessPending} /></div></div>;
  }

  return (
    <div className="app-stage">
      <div className="app-shell">
        {!state.isInitialized ? <InitialSetupScreen error={access.error} isSaving={accessPending} onConfirm={initializeStation} /> : null}
        {state.isInitialized && screen === 'submit' && access.member.role === 'husband' ? <ActionForm onBack={() => navigate('home')} onSubmit={submitAction} pending={actionPending} /> : null}
        {state.isInitialized && screen === 'review' && access.member.role === 'wife' ? <ReviewScreen pending={actionPending} pendingActions={pendingActions} onBack={() => navigate('home')} onDeduct={addDeduction} onResolve={resolveAction} /> : null}
        {state.isInitialized && screen === 'repair' ? <RepairScreen event={activeRepair} onBack={() => navigate('home')} onComplete={completeRepair} onSubmit={submitRepair} pending={actionPending} role={access.member.role} /> : null}
        {state.isInitialized && screen === 'home' ? <HomeScreen onNavigate={navigate} pendingCount={pendingActions.length} repair={activeRepair} role={access.member.role} state={state} /> : null}
        {state.isInitialized && screen === 'ledger' ? <LedgerScreen actions={state.actions} /> : null}
        {state.isInitialized && screen === 'us' ? <UsScreen initialScore={state.initialScore} mileage={state.mileage} role={access.member.role} onReview={() => navigate('review')} /> : null}
        {state.isInitialized && ['home', 'ledger', 'us'].includes(screen) ? <BottomNav current={navScreen} onNavigate={navigate} /> : null}
        <Toast message={toast} />
      </div>
    </div>
  );
}
