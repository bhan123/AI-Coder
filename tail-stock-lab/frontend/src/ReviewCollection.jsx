import { Fragment, useState } from 'react'
import { loadReviewCollectionJobs, loadReviewCollectionAttempts } from './api'
import { useRemote } from './use-remote'
import { collectionQuery, collectionPageError, collectionAvailability, COLLECTION_PAGE_SIZE, COLLECTION_STATUSES } from './review-collection'
import { reviewTimestamp } from './review-center'

const jobKey = job => JSON.stringify([job.trade_date, job.code, job.provider])
const timeLabel = value => value && reviewTimestamp(value) != null ? new Date(reviewTimestamp(value)).toLocaleString('zh-CN', { timeZone:'Asia/Shanghai', hour12:false }) : '未记录'
const attemptLabels = { ...COLLECTION_STATUSES, abandoned:'已中断，后续接续' }
const diagnosticLabels = { unknown_queue_status:'历史队列状态无法识别', invalid_queue_timestamp:'时间缺失、无时区或格式无效' }

function QueueRequestState({ resource, retry }) {
  if (resource.loading) return <p className="rc-empty" role="status">正在读取补采记录…</p>
  if (resource.error) return <div className="rc-message rc-error" role="alert"><strong>补采记录读取失败，不代表没有任务。</strong><p>{resource.error}</p><button onClick={retry}>重试读取补采记录</button></div>
  return null
}

function Pagination({ data, offset, setOffset, kind }) {
  return <div className="rc-pagination"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - COLLECTION_PAGE_SIZE))}>上一页{kind}</button><span>第 {Math.floor(offset / COLLECTION_PAGE_SIZE) + 1} 页</span><button disabled={data.next_offset == null} onClick={() => setOffset(data.next_offset)}>下一页{kind}</button></div>
}

function AttemptHistory({ job, revision }) {
  const [offset, setOffset] = useState(0)
  const [reload, setReload] = useState(0)
  const resource = useRemote(loadReviewCollectionAttempts, { trade_date:job.trade_date, code:job.code, provider:job.provider, limit:COLLECTION_PAGE_SIZE, offset }, revision + reload)
  const error = resource.data ? collectionPageError(resource.data, 'attempts') : ''
  const data = resource.data && !error ? resource.data : null
  return <section className="rc-queue-detail" aria-label="采集尝试记录"><div className="rc-panel-head"><div><h4>{job.code} · 采集尝试记录</h4><p>{job.trade_date} · {job.provider} · 从新到旧，只读保留失败与恢复过程</p></div><button onClick={() => setReload(x => x + 1)}>刷新尝试记录</button></div>
    <QueueRequestState resource={resource} retry={() => setReload(x => x + 1)} />
    {error && <p className="rc-message rc-error" role="alert">{error}</p>}
    {data && <><p className="rc-queue-note">共 {data.total} 次尝试；“完成”仅指采集任务，不代表涨停等全部指标已有证据。</p>
      <div className="table-wrap"><table className="rc-attempt-table"><thead><tr><th>尝试时间</th><th>结束时间</th><th>结果</th><th>错误类别 / 证据</th></tr></thead><tbody>
        {data.items.map(item => <tr key={item.sequence}><td>{timeLabel(item.attempted_at)}</td><td>{timeLabel(item.finished_at)}</td><td>{attemptLabels[item.status] || '状态待核查'}</td><td>{item.error_type || '—'}{item.evidence_id && <details><summary>证据编号</summary><code className="rc-queue-evidence-id">{item.evidence_id}</code></details>}</td></tr>)}
        {!data.items.length && <tr><td colSpan="4" className="rc-empty">尚无匹配的采集尝试，不能据此判断数据已齐。</td></tr>}
      </tbody></table></div>
      <Pagination data={data} offset={offset} setOffset={setOffset} kind="尝试" />
    </>}
  </section>
}

export default function ReviewCollection({ range, revision }) {
  const [filters, setFilters] = useState({ code:'', status:'' })
  const [draft, setDraft] = useState(filters)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState(null)
  const [reload, setReload] = useState(0)
  const [validation, setValidation] = useState('')
  const resource = useRemote(loadReviewCollectionJobs, collectionQuery(range, { ...filters, offset }), revision + reload)
  const error = resource.data ? collectionPageError(resource.data) : ''
  const data = resource.data && !error ? resource.data : null
  const pending = draft.code !== filters.code || draft.status !== filters.status

  function apply(event) {
    event.preventDefault()
    try {
      const next = collectionQuery(range, draft)
      setFilters({ code:next.code, status:next.status }); setDraft({ code:next.code, status:next.status })
      setOffset(0); setSelected(null); setValidation(''); setReload(x => x + 1)
    } catch (error) { setValidation(error.message) }
  }
  function reset() {
    setFilters({code:'',status:''}); setDraft({code:'',status:''}); setOffset(0); setSelected(null); setValidation(''); setReload(x => x + 1)
  }
  function pageTo(next) { setOffset(next); setSelected(null) }

  return <section className="rc-collection" aria-label="收盘补采诊断"><div className="rc-panel-head rc-queue-heading"><div><h2>收盘补采诊断</h2><p>共享队列，不按策略过滤。日期为目标收盘日，包含 V1 次日目标，不完全等于推荐日。</p><p>当前日期范围：{range.date_from} — {range.date_to} · 只读查询，不触发重采。</p></div><button onClick={() => { setSelected(null); setReload(x => x + 1) }}>刷新任务</button></div>
    <form className="rc-filters rc-queue-filters" onSubmit={apply}><label>股票代码<input aria-label="补采股票代码" inputMode="numeric" maxLength={6} placeholder="六位代码" value={draft.code} onChange={e => setDraft({ ...draft, code:e.target.value })} /></label><label>采集状态<select aria-label="补采状态" value={draft.status} onChange={e => setDraft({ ...draft, status:e.target.value })}><option value="">全部状态</option>{Object.entries(COLLECTION_STATUSES).map(([value,label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="rc-primary" type="submit">筛选任务</button><button type="button" onClick={reset}>重置任务筛选</button></form>
    {validation && <p className="rc-message rc-error" role="alert">{validation}</p>}
    {pending && !validation && <p className="rc-muted" role="status">任务筛选已修改，点击“筛选任务”后生效。</p>}
    <QueueRequestState resource={resource} retry={() => setReload(x => x + 1)} />
    {error && <p className="rc-message rc-error" role="alert">{error}</p>}
    {data && <section className="rc-panel"><div className="rc-panel-head"><div><h3>匹配任务 {data.total}</h3><p>查询时刻：{timeLabel(data.as_of)} · 统计包含全部匹配任务，不仅是当前页。</p></div><div className="rc-queue-counts">{Object.entries(data.counts_by_status).map(([status,count]) => <span key={status}>{COLLECTION_STATUSES[status] || '未知状态'} <strong>{count}</strong></span>)}</div></div>
      {data.queue_status === 'not_initialized' ? <p className="rc-empty">尚未建立补采队列；不能据此判断所有复盘数据已经齐全。</p> : <div className="table-wrap"><table className="rc-queue-table"><thead><tr><th>股票 / 来源</th><th>目标收盘日</th><th>当前状态</th><th>尝试次数</th><th>最近错误类别</th><th>时间条件</th><th>记录</th></tr></thead><tbody>
        {data.items.map(job => { const key=jobKey(job), state=collectionAvailability(job), expanded=selected===key; return <Fragment key={key}><tr><td><strong>{job.code}</strong><small>{job.provider}</small></td><td>{job.trade_date}</td><td><span className={`rc-queue-status ${state.tone}`}>{state.label}</span><small>{COLLECTION_STATUSES[job.status] || '原状态未知'}</small></td><td>{job.attempt_count}</td><td>{job.last_error_type || '—'}</td><td>{job.next_eligible_at ? timeLabel(job.next_eligible_at) : '—'}<small>更新 {timeLabel(job.updated_at)}</small></td><td><button aria-label={`查看 ${job.code} 补采记录`} aria-expanded={expanded} onClick={() => setSelected(expanded ? null : key)}>{expanded ? '收起' : '查看'}</button></td></tr>
          {expanded && <tr className="rc-detail-row"><td colSpan="7"><div className="rc-queue-explanation"><p>{state.note}</p>{!!job.diagnostic_flags?.length && <p>{job.diagnostic_flags.map(flag => diagnosticLabels[flag] || '未识别的诊断标记').join('；')}</p>}</div><AttemptHistory key={`${key}:${revision}:${reload}`} job={job} revision={revision + reload} /></td></tr>}</Fragment> })}
        {!data.items.length && <tr><td colSpan="7" className="rc-empty">当前筛选没有匹配任务，不代表所有复盘证据已经齐全。</td></tr>}
      </tbody></table></div>}
      <Pagination data={data} offset={offset} setOffset={pageTo} kind="任务" />
      <p className="rc-queue-note">时间条件不是下一次服务器调度时刻，也不保证行情就绪。跨页查询期间队列可能变化；需要最新状态时请刷新。</p>
    </section>}
  </section>
}
