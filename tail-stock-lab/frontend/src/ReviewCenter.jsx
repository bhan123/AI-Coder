import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { loadReviewSummary, loadReviewReports, loadReviewReport, loadReviewAutomation } from './api'
import { defaultReviewRange, validateReviewRange, metricView, sortReviewEvents, issueGroups, reviewTimestamp, reviewPresetRange, latestMarketObservation, FLAG_LABELS, STRATEGY_NAMES } from './review-center'
import './review-center.css'
import { useRemote } from './use-remote'
import ReviewCollection from './ReviewCollection'

const EMPTY = []
const METRICS = [
  ['close_positive_rate', '收盘高于首次价', '只比较价格，不代表交易盈利率。'],
  ['post_alert_limit_rate', '预警后触板率', '需要真实涨停价和先后顺序证据。'],
  ['close_limit_rate', '收盘封板率', '需要收盘价及当日真实涨停价。'],
]
const statusLabel = { incomplete: '证据未齐', zero_signals: '成功运行 · 零信号', no_run_evidence: '无运行证据' }
const timeLabel = value => value && reviewTimestamp(value) != null ? new Date(reviewTimestamp(value)).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '未知'
const pct = value => Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%` : '未知'
const price = value => value != null && Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '未知'
const tone = value => Number.isFinite(value) ? value > 0 ? 'rc-up' : value < 0 ? 'rc-down' : '' : 'rc-muted'

function RequestState({ resource, retry }) {
  if (resource.loading) return <p className="rc-empty" role="status">正在读取复盘证据…</p>
  if (resource.error) return <div className="rc-message rc-error" role="alert"><strong>读取失败，不能据此判断零预警。</strong><p>{resource.error}</p><button onClick={retry}>重新读取</button></div>
  return null
}

function Evidence({ event }) {
  const record = event.closing_evidence
  const quotes = record?.conflict ? record.candidates : record ? [record] : []
  const signal = event.trigger_signal
  return <>{event.strategy_id === 'fishing-reversal' && <>
    <StockAnalysis analysis={event.next_day_analysis} heading="V1 次日偏离分析" missingMessage="此历史快照尚无V1次日偏离分析；补齐证据后重新生成报告会追加新修订，不改写旧报告。" />
    <NextDayClose outcome={event.next_day_close} /><T1Review review={event.t1_review} />
  </>}<StockAnalysis analysis={event.analysis} /><div className="rc-evidence">
    <section><h4>首次信号记录</h4><p>{timeLabel(event.first_at)} · 参考价 {price(event.first_price)}</p>
      <p>来源：{event.data_source || '未知'} · 策略版本：{event.versions?.join(' / ') || '未知'}</p>
      <p>当时规则记录：{signal?.reason || '未留档'}</p>
      <dl>{(signal?.factors || []).map((factor, index) => <Fragment key={index}><dt>{factor.label}</dt><dd>{String(factor.value ?? '未知')}</dd></Fragment>)}</dl>
      <details><summary>查看首次信号原始记录</summary><pre>{JSON.stringify(signal || {}, null, 2)}</pre></details>
    </section>
    <section><h4>收盘与后续观测</h4><p>盘中末次：{timeLabel(event.last_observed_at)} · {price(event.last_observed_price)}（{pct(event.last_observed_return_pct)}）</p>
      {!quotes.length && <p>尚无收盘证据；不会用盘中末次价格代替。</p>}
      {quotes.map(item => <div className="rc-source" key={item.evidence_id}><p>{item.quote.source} · 收盘 {price(item.quote.close)}</p>
        <p>采集：{timeLabel(item.quote.fetched_at)} · 入库：{timeLabel(item.received_at)}</p>
        <p>时间依据：{item.quote.price_time_basis === 'daily_session_end' ? '日线时段终点，非供应商逐笔时间' : '来源时间戳'} · 不复权</p>
        <details><summary>查看来源与证据编号</summary><pre>{JSON.stringify(item, null, 2)}</pre></details></div>)}
      <p>记录标记：{(event.quality_flags || []).map(flag => FLAG_LABELS[flag] || flag).join('；') || '无已记录标记'}</p>
      <p className="rc-muted">原始记录用于核对上方分析，不能单凭价格回落确认下跌原因。</p>
    </section>
  </div></>
}

function NextDayClose({ outcome }) {
  const labels = { calendar_unknown: '日历未覆盖或推荐日期异常，次日结果保持未知。', not_yet_closed: '下一计划交易日尚未收盘。', pending_close: '等待次日收盘证据，不用盘中价格代替。', closing_source_conflict: '次日收盘来源冲突，结果保持未知。', invalid_first_price: '首次参考价无效，不能计算相对变化。', close_available: '已取得下一计划交易日收盘证据' }
  const record = outcome?.closing_evidence
  const quote = record && !record.conflict ? record.quote : null
  return <section className="rc-analysis" aria-label="V1 次日市场收盘"><h3>V1 次日市场收盘</h3>
    {!outcome ? <p>此历史快照未包含次日收盘，不用当前数据补写旧报告。</p> : <>
      <p>{labels[outcome.status] || '结果状态未知'}</p>
      <p>目标日期：{outcome.calendar?.next_date || '未知'} · 日历版本 {outcome.calendar?.version || '未知'}</p>
      {quote && <><p>收盘价 {price(quote.close)} · 相对首次参考价 <strong className={tone(outcome.close_return_pct)}>{pct(outcome.close_return_pct)}</strong></p>
        <p className="rc-muted">来源：{quote.source} · 收盘时点 {timeLabel(quote.price_at)} · 证据入库 {timeLabel(record.received_at)}</p></>}
      {outcome.rule_date_matches_schedule === false && <p className="rc-error">原规则结果日期与日历目标不一致，请核查旧记录。</p>}
      <ul>{(outcome.limitations || []).map(text => <li key={text}>{text}</li>)}</ul>
      <details><summary>查看次日日历与行情证据</summary><pre>{JSON.stringify(outcome, null, 2)}</pre></details>
    </>}
  </section>
}

function T1Review({ review }) {
  const labels = {
    missing: '未找到首次推荐对应的次日规则记录，结果保持未知。',
    not_yet_observable: '统计截止尚未覆盖次日上午规则窗口，暂不展示结果。',
    invalid_record: '记录异常，结果保持未知。',
    recorded_unverified: '已有规则记录 · 下一交易日及历史可见性待核验',
  }
  const exitLabels = { stop_loss: '止损退出', trailing_exit: '回撤退出', morning_cutoff: '上午窗口结束' }
  const rule = review?.status === 'recorded_unverified' ? review.rule_exit : null
  return <section className="rc-analysis" aria-label="V1 次日规则记录"><h3>V1 次日规则记录</h3>
    {!review ? <p>此历史快照未包含次日规则记录，不用当前数据补写旧报告。</p> : <>
      <p>{labels[review.status] || '记录状态无法识别，结果保持未知。'}</p>
      {rule && <><p>记录结果日：{review.recorded_outcome_date} · 原始推荐批次：{review.run_id}</p>
        <p>原规则参考价 {price(rule.entry_price)} → 退出价 {price(rule.exit_price)} · {exitLabels[rule.exit_reason] || '退出原因未知'}</p>
        <p>规则模拟净收益：<strong className={tone(rule.net_return_pct)}>{pct(rule.net_return_pct)}</strong>（原记录值，不计入上方推荐当日收盘统计）</p></>}
      <ul>{(review.limitations || []).map(text => <li key={text}>{text}</li>)}</ul>
    </>}
    <p className="rc-muted">原规则模拟退出与次日市场收盘独立；此处不判断实际交易盈利或下跌原因。</p>
  </section>
}

function StockAnalysis({ analysis, heading = '逐股原因分析', missingMessage = '此历史快照尚无逐股分析，原证据保留；新生成报告将附带分析，不改写旧报告。' }) {
  if (!analysis) return <p className="rc-message rc-analysis">{missingMessage}</p>
  return <section className="rc-analysis" aria-label={heading}><div className="rc-panel-head"><h3>{heading}</h3><span className="rc-muted">证据规则分析 · 非大模型 · v{analysis.version}</span></div>
    <p className="rc-muted">观察口径：{analysis.scope}</p>
    {analysis.target_date && <p>目标交易日：{analysis.target_date} · 收盘相对推荐价 <strong className={tone(analysis.outcome.return_pct)}>{pct(analysis.outcome.return_pct)}</strong> · 相对推荐日收盘 <strong className={tone(analysis.outcome.session_return_pct)}>{pct(analysis.outcome.session_return_pct)}</strong></p>}
    <div className="rc-analysis-grid"><section><h4>当时为什么触发</h4><p>{analysis.trigger.reason}</p><p className="rc-muted">首次运行 {analysis.trigger.run_id || '未知'} · {timeLabel(analysis.trigger.at)}</p>
      <ul>{analysis.trigger.factors.map((factor, index) => <li key={index}><strong>{factor.label}：{String(factor.value ?? '未知')}</strong><span> · 当时贡献 {factor.score ?? '未知'} 分</span><p className="rc-muted">{factor.description}</p></li>)}</ul>
      {!analysis.trigger.factors.length && <p>当时未留存因子明细，不使用当前阈值补写历史原因。</p>}
    </section><section><h4>后来实际发生什么</h4><ul>{analysis.facts.map((fact, index) => <li key={fact.key || index}>{fact.text}{fact.at && <small> · {timeLabel(fact.at)}</small>}
      {!!fact.evidence_ids?.length && <details><summary>核对证据编号</summary><pre>{fact.evidence_ids.join('\n')}{fact.signal_run_id ? `\n首次批次：${fact.signal_run_id}` : ''}</pre><small>与下方次日收盘、推荐日收盘及首次信号原始记录对应。</small></details>}
    </li>)}</ul><p><strong>{analysis.conclusion}</strong></p></section></div>
    {!!analysis.patterns?.length && <section><h4>已观察到的偏离形态 · 不是下跌成因</h4><ul>{analysis.patterns.map(item => <li key={item.key}>{item.text}</li>)}</ul></section>}
    {!!analysis.hypotheses.length && <section className="rc-hypotheses"><h4>为什么偏离：待核查，尚非结论</h4>{analysis.hypotheses.map(item => <div key={item.key}><strong>{item.question}</strong><p>所需证据：{item.required}</p></div>)}</section>}
    {!!analysis.data_gaps?.length && <section><h4>尚缺的证据</h4><ul>{analysis.data_gaps.map(item => <li key={item.key}>{item.text}</li>)}</ul></section>}
    <details><summary>分析边界</summary><ul>{analysis.limitations.map(text => <li key={text}>{text}</li>)}</ul></details>
  </section>
}

function AutomationStatus({ revision }) {
  const [reload, setReload] = useState(0)
  const resource = useRemote(loadReviewAutomation, {}, revision + reload)
  const labels = { completed:'执行完成', partial:'部分完成，仍有待补或失败项', failed:'执行失败', interrupted:'运行中断', running:'执行中', abandoned:'上次中断，已由后续运行接续', lease_expired:'运行超时，等待接续' }
  const state = resource.data
  return <section className="rc-panel rc-automation"><div className="rc-panel-head"><h3>自动报告运行</h3><button onClick={() => setReload(x => x + 1)}>刷新运行记录</button></div>
    {resource.loading && <p role="status">正在读取自动报告状态…</p>}
    {resource.error && <p role="alert" className="rc-error">自动报告状态读取失败：{resource.error}。不能据此判断任务未启用。</p>}
    {state && <><p>上海时间：工作日16:30日报 · 周五18:00周报；定时检查与补采重试，默认回看最近7个自然日。</p>
      <p className="rc-muted">{state.note} 执行完成不代表行情证据齐全；节假日可能产生“无运行证据”报告。</p>
      {!state.last_run ? <p>尚无自动报告运行记录。部署配置已提供，服务器启用状态未核验。</p> : <><p><strong>最近运行：{labels[state.last_run.status] || state.last_run.status}</strong> · {timeLabel(state.last_run.started_at)}</p>
        <details><summary>最近执行记录（最多10次）</summary><ul>{state.recent_runs.map((run, index) => <li key={index}>{timeLabel(run.started_at)} · {labels[run.status] || run.status} · 处理 {run.result?.reports?.length ?? 0} 份报告
          {run.result?.collection && <p>收盘补采：完成 {run.result.collection.completed} / 失败 {run.result.collection.failed} / 待续 {run.result.collection.deferred}</p>}
          {!!run.result?.errors?.length && <p className="rc-error">错误：{run.result.errors.map(error => `${error.stage} / ${error.type}`).join('；')}</p>}
        </li>)}</ul></details></>}
    </>}
  </section>
}

function EventTable({ events, initialFlag = '' }) {
  const [sort, setSort] = useState({ field: 'first_at', direction: 'desc' })
  const [expanded, setExpanded] = useState(null)
  const [search, setSearch] = useState('')
  const [outcome, setOutcome] = useState('all')
  const [page, setPage] = useState(0)
  const rows = useMemo(() => sortReviewEvents(events.filter(event =>
    (!initialFlag || event.quality_flags?.includes(initialFlag)) &&
    `${event.code} ${event.name}`.includes(search.trim()) &&
    (outcome === 'all' || (outcome === 'unknown' ? event.close_positive == null : event.close_positive === (outcome === 'up')))
  ), sort.field, sort.direction), [events, initialFlag, search, outcome, sort])
  const currentPage = Math.min(page, Math.max(0, Math.ceil(rows.length / 25) - 1))
  function header(label, field) {
    const active = sort.field === field
    return <th scope="col" aria-sort={active ? sort.direction === 'asc' ? 'ascending' : 'descending' : 'none'}><button className="rc-sort" onClick={() => { setSort({ field, direction: active && sort.direction === 'desc' ? 'asc' : 'desc' }); setPage(0) }}>{label}<span aria-hidden="true" className="sort-triangles"><span className="sort-triangle" data-active={active && sort.direction === 'asc'}>▲</span><span className="sort-triangle" data-active={active && sort.direction === 'desc'}>▼</span></span></button></th>
  }
  return <section className="rc-panel"><div className="rc-panel-head"><div><h3>逐股复盘</h3><p>表格筛选不改变上方总体指标 · {rows.length} / {events.length} 条</p></div>
    <div className="rc-inline"><input aria-label="搜索复盘股票" placeholder="代码或名称" value={search} onChange={e => { setSearch(e.target.value); setPage(0) }} />
      <select aria-label="收盘结果筛选" value={outcome} onChange={e => { setOutcome(e.target.value); setPage(0) }}><option value="all">全部收盘结果</option><option value="up">高于首次价</option><option value="not-up">未高于首次价</option><option value="unknown">未知</option></select></div></div>
    <div className="table-wrap"><table className="rc-event-table"><thead><tr>{header('首次信号', 'first_at')}<th scope="col">股票 / 首次价</th>{header('首次规则分', 'first_score')}{header('收盘相对首次价', 'close_return_pct')}<th scope="col">触板 / 封板</th><th scope="col">证据</th></tr></thead><tbody>
      {rows.slice(currentPage * 25, currentPage * 25 + 25).map(event => <Fragment key={event.event_id}><tr>
        <td>{timeLabel(event.first_at)}</td><td><strong>{event.code} {event.name}</strong><small>首次 {price(event.first_price)}</small></td><td>{event.first_score ?? '未知'}</td>
        <td className={tone(event.close_return_pct)}>{pct(event.close_return_pct)}</td><td>{event.post_alert_limit == null ? '未知' : event.post_alert_limit ? '已触板' : '未触板'} / {event.close_limit == null ? '未知' : event.close_limit ? '封板' : '未封板'}</td>
        <td><button aria-expanded={expanded === event.event_id} aria-label={`查看 ${event.code} 复盘证据`} onClick={() => setExpanded(expanded === event.event_id ? null : event.event_id)}>{expanded === event.event_id ? '收起' : '查看证据'}</button></td>
      </tr>{expanded === event.event_id && <tr className="rc-detail-row"><td colSpan="6"><Evidence event={event} /></td></tr>}</Fragment>)}
      {!rows.length && <tr><td colSpan="6" className="rc-empty">当前条件下没有可展示的事件。</td></tr>}
    </tbody></table></div>
    {rows.length > 25 && <div className="rc-pagination"><button disabled={!currentPage} onClick={() => setPage(currentPage - 1)}>上一页</button><span>{currentPage + 1} / {Math.ceil(rows.length / 25)}</span><button disabled={(currentPage + 1) * 25 >= rows.length} onClick={() => setPage(currentPage + 1)}>下一页</button></div>}
  </section>
}

function ReportBody({ report, gaps = false }) {
  const [flag, setFlag] = useState('')
  const events = report.events || EMPTY
  const groups = useMemo(() => issueGroups(events), [events])
  const missingDays = report.coverage?.dates_without_run_evidence || EMPTY
  const observed = latestMarketObservation(report)
  return <>
    <div className="rc-context"><span>{STRATEGY_NAMES[report.strategy_id]} · {report.date_from} — {report.date_to}</span><span>统计截止 {timeLabel(report.as_of)} · 计算版本 {report.calculation_version}</span></div>
    <p className="rc-muted">最新行情观测：{observed == null ? '无观测记录' : timeLabel(new Date(observed).toISOString())}。刷新统计不会刷新原始行情。</p>
    <div className="rc-message"><strong>{statusLabel[report.status] || report.status}</strong><span> · {report.event_count} 个去重事件 / {report.scan_count} 次正式运行</span>
      <p>同一策略、股票和交易日只计首次正式信号。未知不计成功，也不计失败；历史发布时间缺失时，不代表用户可执行收益。</p>
      {report.strategy_id === 'fishing-reversal' && <p><strong>常规收盘指标及表格收盘列均为推荐当日表现。</strong> 次日市场收盘与原规则退出在股票展开区分别展示，不混算三种口径。</p>}
    </div>
    {!gaps ? <>
      {report.strategy_id === 'fishing-reversal' && report.next_day_metrics && <section className="rc-panel"><h3>V1 次日收盘表现</h3><p>{report.next_day_metrics.definition}</p>
        <p><strong>{metricView(report.next_day_metrics.close_positive_rate).value}</strong> · 高于首次价 / 有效 {metricView(report.next_day_metrics.close_positive_rate).denominator} · 未知 {metricView(report.next_day_metrics.close_positive_rate).unknown} · 覆盖 {metricView(report.next_day_metrics.close_positive_rate).coverage}</p>
        <p className="rc-muted">日历按已公布沪深2026年安排；未覆盖日期及缺证据记录不计成功或失败，不确认个股可成交。</p></section>}
      {report.strategy_id === 'fishing-reversal' && report.t1_summary && <section className="rc-panel"><h3>次日规则记录覆盖</h3><p>共 {report.t1_summary.event_count} 条 · 已关联但待核验 {report.t1_summary.recorded_unverified} · 缺记录 {report.t1_summary.missing} · 记录异常 {report.t1_summary.invalid_record} · 窗口未到 {report.t1_summary.not_yet_observable}</p><p className="rc-muted">这里只统计记录完整度，不是策略胜率。</p></section>}
      {report.next_day_analysis_summary && <NextDayAnalysisSummary summary={report.next_day_analysis_summary} />}
      {report.review_summary && <section className="rc-panel rc-report-summary"><h3>本期复盘摘要{report.strategy_id === 'fishing-reversal' ? ' · 推荐当日' : ''}</h3><p>{report.review_summary.conclusion}</p><p>有效收盘：上涨 {report.review_summary.close_up_count} · 下跌 {report.review_summary.close_down_count} · 持平 {report.review_summary.close_flat_count} · 未知 {report.review_summary.close_unknown_count}</p><details><summary>下一步核查建议（不自动调整策略）</summary><ul>{report.review_summary.next_checks.map(text => <li key={text}>{text}</li>)}</ul></details></section>}
      <div className="rc-metrics">{METRICS.map(([key, label, note]) => { const metric = metricView(report.metrics?.[key]); return <article key={key}><h3>{label}</h3><strong>{metric.value}</strong><p>成功 / 有效：{metric.denominator}</p><p>未知 {metric.unknown} · 覆盖 {metric.coverage}</p><small>{note}</small></article> })}</div>
      <EventTable events={events} />
    </> : <>
      <section className="rc-panel rc-gaps"><h3>数据缺口清单</h3><p>以下是记录完整度问题，不是股价下跌的原因。标签可重叠，数量不相加为事件总数。</p>
        <div className="rc-gap-list"><button className={!flag ? 'active' : ''} onClick={() => setFlag('')}>全部事件 · {events.length}</button>{groups.map(group => <button className={flag === group.flag ? 'active' : ''} key={group.flag} onClick={() => setFlag(group.flag)}>{FLAG_LABELS[group.flag] || group.flag}<strong>{group.count}</strong></button>)}</div>
        <details><summary>无运行证据日期 · {missingDays.length} 天</summary><p>{missingDays.join('、') || '所选日期均有运行记录。'}</p></details>
        {!report.coverage?.calendar_verified && <p>交易日历尚未核验：没有运行记录不等于扫描失败，也不能据此判断休市。</p>}
      </section><EventTable key={flag} events={events} initialFlag={flag} />
    </>}
  </>
}

function NextDayAnalysisSummary({ summary }) {
  return <section className="rc-panel rc-report-summary" aria-label="V1 次日偏离摘要"><h3>V1 次日偏离摘要</h3>
    <p>共 {summary.event_count} 条 · 收盘低于推荐价 {summary.below_reference_count} · 次日结果未知 {summary.unknown_count}</p>
    <p>相对推荐日收盘下跌 {summary.session_decline_count} · 该口径未知 {summary.session_unknown_count}</p>
    <p>成因待核查 {summary.unresolved_cause_count} · 已确认成因 {summary.confirmed_cause_count}</p>
    <ul>{summary.patterns.map(item => <li key={item.key}>{item.text} · {item.count} 条</li>)}</ul>
    <p className="rc-muted">{summary.note}</p>
  </section>
}

function ArchivedReport({ id, onClose }) {
  const [revision, setRevision] = useState(0)
  const resource = useRemote(loadReviewReport, id, revision)
  const ref = useRef(null)
  useEffect(() => { ref.current?.scrollIntoView({ block: 'start', behavior: 'auto' }); ref.current?.focus() }, [id, ref])
  return <div className="rc-archive-detail" ref={node => { ref.current = node }} tabIndex="-1"><div className="rc-panel-head"><h3>归档报告 · 原始修订快照</h3><button onClick={onClose}>关闭报告</button></div>
    <RequestState resource={resource} retry={() => setRevision(x => x + 1)} />
    {resource.data && <><p className="rc-muted">修订 {resource.data.revision} · 生成于 {timeLabel(resource.data.created_at)} · 不随当前行情变化</p><ReportBody report={resource.data.report} /></>}
  </div>
}

function ReportArchive({ query, revision }) {
  const [selected, setSelected] = useState(null)
  const [reload, setReload] = useState(0)
  const [period, setPeriod] = useState('')
  const [latestOnly, setLatestOnly] = useState(true)
  const [offset, setOffset] = useState(0)
  const resource = useRemote(loadReviewReports, { ...query, period, latest_only: latestOnly, limit: 25, offset }, revision + reload)
  const rows = resource.data?.reports || EMPTY
  function changeFilter(setter, value) { setter(value); setOffset(0); setSelected(null) }
  return <>
      <AutomationStatus revision={revision} />
      <div className="rc-panel-head rc-archive-controls"><div><h3>报告归档</h3><p>{STRATEGY_NAMES[query.strategy_id]} · {query.date_from} — {query.date_to}<br />按报告区间相交查询全部归档，不受最近50份限制。报告保留原始修订，补齐证据后生成新修订。</p></div>
      <div className="rc-inline"><label>报告周期<select aria-label="报告周期" value={period} onChange={e => changeFilter(setPeriod, e.target.value)}><option value="">日报与周报</option><option value="daily">仅日报</option><option value="weekly">仅周报</option></select></label>
        <label>修订范围<select aria-label="报告修订范围" value={latestOnly ? 'latest' : 'all'} onChange={e => changeFilter(setLatestOnly, e.target.value === 'latest')}><option value="latest">每份报告最新修订</option><option value="all">全部历史修订</option></select></label></div>
    </div>
    <RequestState resource={resource} retry={() => setReload(x => x + 1)} />
    {resource.data && !Number.isFinite(resource.data.total) && <p role="alert" className="rc-message rc-error">归档接口版本不匹配，请更新后端后重试；不能据此判断没有报告。</p>}
    {resource.data && Number.isFinite(resource.data.total) && <section className="rc-panel"><div className="rc-panel-head"><p>共 {resource.data.total} 份{latestOnly ? '最新修订' : '修订记录'} · 按生成时间从新到旧排列</p></div>
      <div className="table-wrap"><table className="rc-archive-table"><thead><tr><th>观察区间</th><th>周期</th><th>修订</th><th>事件数</th><th>状态</th><th>生成时间</th><th>报告</th></tr></thead><tbody>
        {rows.map(row => <tr key={row.report_id}><td>{row.date_from} — {row.date_to}</td><td>{row.period === 'daily' ? '日报' : '周报'}</td><td>v{row.revision}</td><td>{row.event_count}</td><td>{statusLabel[row.status] || row.status}</td><td>{timeLabel(row.created_at)}</td><td><button onClick={() => setSelected(row.report_id)}>查看报告</button></td></tr>)}
        {!rows.length && <tr><td colSpan="7" className="rc-empty">当前范围没有已归档报告，不代表没有预警。</td></tr>}
      </tbody></table></div>
      <div className="rc-pagination"><button disabled={!offset || resource.loading} onClick={() => {setOffset(Math.max(0, offset - 25)); setSelected(null)}}>上一页报告</button><span>第 {Math.floor(offset / 25) + 1} 页</span><button disabled={!resource.data.has_more || resource.loading} onClick={() => {setOffset(offset + 25); setSelected(null)}}>下一页报告</button></div>
    </section>}
    {selected && <ArchivedReport key={selected} id={selected} onClose={() => setSelected(null)} />}
  </>
}

export default function ReviewCenter() {
  const [query, setQuery] = useState(() => ({ strategy_id: 'limit-up-ambush', ...defaultReviewRange() }))
  const [draft, setDraft] = useState(query)
  const [tab, setTab] = useState('summary')
  const [validation, setValidation] = useState('')
  const [revision, setRevision] = useState(0)
  const resource = useRemote(loadReviewSummary, query, revision)
  const pending = JSON.stringify(draft) !== JSON.stringify(query)
  function preset(days) { const next = { ...draft, ...reviewPresetRange(days) }; setDraft(next); setQuery(next); setValidation(''); setRevision(x => x + 1) }
  function apply(event) { event.preventDefault(); const error = validateReviewRange(draft.date_from, draft.date_to); setValidation(error); if (!error) { setQuery({ ...draft }); setRevision(x => x + 1) } }
  return <div className="review-center"><header className="rc-header"><div><span className="eyebrow">SIGNAL REVIEW</span><h1>复盘与诊断</h1><p>把信号后的表现、证据和未知分开看。</p></div><span className="rc-readonly">只读分析 · 不改变策略</span></header>
    <form className="rc-filters" onSubmit={apply}><label>{tab === 'collection' ? '共享队列（不按策略过滤）' : '策略'}<select aria-label="复盘策略" disabled={tab === 'collection'} value={draft.strategy_id} onChange={e => setDraft({ ...draft, strategy_id: e.target.value })}>{Object.entries(STRATEGY_NAMES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>起始日期<input type="date" value={draft.date_from} onChange={e => setDraft({ ...draft, date_from: e.target.value })} /></label><label>结束日期<input type="date" value={draft.date_to} onChange={e => setDraft({ ...draft, date_to: e.target.value })} /></label>
      <button type="submit" className="rc-primary">查询复盘</button><button type="button" onClick={() => setRevision(x => x + 1)}>刷新当前结果</button></form>
    <div className="rc-presets"><span>截至昨日：</span>{[[1, '昨日'], [7, '近7天'], [30, '近30天']].map(([days, label]) => <button key={days} onClick={() => preset(days)}>{label}</button>)}<span>自然日范围，非交易日数</span></div>
    {pending && <p className="rc-message" role="status">筛选条件已修改，点击“查询复盘”后生效。</p>}
    {validation && <p role="alert" className="rc-error">{validation}</p>}
    <div className="rc-tabs" role="group" aria-label="复盘视图">{[['summary', '效果总览'], ['archive', '报告归档'], ['gaps', '数据缺口'], ['collection', '补采诊断']].map(([id, name]) => <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{name}</button>)}</div>
    {tab === 'collection' ? <ReviewCollection key={`${query.date_from}:${query.date_to}`} range={query} revision={revision} /> : tab === 'archive' ? <ReportArchive key={JSON.stringify(query)} query={query} revision={revision} /> : <>
      <RequestState resource={resource} retry={() => setRevision(x => x + 1)} />
      {resource.data && <ReportBody key={`${JSON.stringify(query)}:${tab}`} report={resource.data} gaps={tab === 'gaps'} />}
    </>}
  </div>
}
