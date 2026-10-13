import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import {
  loadAlertHistory,
  loadHistoricalRun,
  loadHistory,
  loadLatestAlert,
  loadLatestForStrategy,
  loadStrategy,
  loadStrategyConfig,
  loadT1Review,
  saveStrategyConfig,
} from './api'
import { dailyHistoryRows } from './history'
import { relativeAlertMove, sortAlertEvents } from './alert-history'
import { PRIMARY_STRATEGY_ID, VISIBLE_STRATEGY_TABS } from './strategy-tabs'
import { buildT1Chart } from './t1-review-chart'
import ReviewCenter from './ReviewCenter'

const riskLabel = { low: '低', medium: '中等', high: '较高' }

const STRATEGY_TABS = VISIBLE_STRATEGY_TABS

const HISTORY_STATUS_LABEL = {
  tradable: '可执行',
  outside_tail_window: '非可执行时段',
}

const ALERT_RESULT_LABEL = {
  watching: '跟踪中',
  hit_limit: '触及涨停',
  not_hit: '未触及',
}

const EMPTY_POINTS = []

function ConfigDrawer({ strategy, onClose }) {
  const [config, setConfig] = useState(strategy?.config || {})
  const [pending, setPending] = useState({})
  const [savedAt, setSavedAt] = useState(null)
  const [saving, setSaving] = useState(false)

  if (!strategy) return null

  const apply = async () => {
    setSaving(true)
    try {
      const result = await saveStrategyConfig(strategy.id, pending)
      setConfig(result.config)
      setPending({})
      setSavedAt(new Date().toLocaleTimeString('zh-CN'))
    } catch (error) {
      alert(error.message)
    } finally {
      setSaving(false)
    }
  }

  return <div className="config-drawer">
    <div className="drawer-head">
      <h3>{strategy.name} · 调参</h3>
      <button onClick={onClose}>×</button>
    </div>
    <p className="muted">覆盖字段会立即生效，下次跑策略按新阈值判定。非法字段会被忽略。</p>
    <div className="config-grid">
      {Object.entries(config).map(([key, value]) => (
        <label key={key}>
          <span>{key}</span>
          <input
            value={pending[key] ?? value}
            type={typeof value === 'number' ? 'number' : 'text'}
            step="any"
            onChange={(e) => {
              const raw = e.target.value
              const next = typeof value === 'number' ? Number(raw) : raw
              setPending((prev) => ({ ...prev, [key]: Number.isNaN(next) ? raw : next }))
            }}
          />
        </label>
      ))}
    </div>
    <div className="drawer-foot">
      {savedAt && <span className="muted">已保存 {savedAt}</span>}
      <button onClick={apply} disabled={saving || Object.keys(pending).length === 0}>
        {saving ? '保存中…' : '应用覆盖'}
      </button>
    </div>
  </div>
}

function formatTime(value) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '尚未运行'
}

function historyDate(value) {
  return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'short' }).format(new Date(value))
}

function historyClock(value) {
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}

const exitReasonLabel = {
  stop_loss: '止损退出',
  trailing_exit: '回撤止盈',
  morning_cutoff: '10:30 截止',
}

function formatPrice(value) {
  return typeof value === 'number' ? value.toFixed(2) : '—'
}

function formatPercent(value) {
  if (typeof value !== 'number') return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`
}

function reviewClock(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
}

function T1MarketChart({ trade }) {
  const chart = buildT1Chart(trade.market_review, [
    { label: '推荐价', price: trade.entry_price },
    { label: '规则退出', price: trade.exit_price },
  ])
  if (!chart) return <p className="review-chart-pending">全天分时将在次日 14:50 自动归档；旧记录没有该数据。</p>

  return <section className="review-chart-card" aria-label={`${trade.code} 次日分时走势`}>
    <div className="review-chart-heading">
      <div>
        <strong>{trade.code} {trade.name}</strong>
        <small>次日分时 / K 线口径 · 截至 {reviewClock(trade.market_review.observed_at)}</small>
      </div>
      <div className="review-rule-result">
        <span>规则退出 {formatPrice(trade.exit_price)}</span>
        <strong>{exitReasonLabel[trade.exit_reason] || trade.exit_reason}</strong>
      </div>
    </div>
    <div className="review-chart-stats">
      <span>开 {formatPrice(chart.openPrice)}</span><span>高 {formatPrice(chart.highPrice)}</span>
      <span>低 {formatPrice(chart.lowPrice)}</span><span>截至 {formatPrice(chart.lastPrice)}</span>
    </div>
    <svg className="review-chart" viewBox={`0 0 ${chart.width} ${chart.height}`} role="img" aria-label={`${trade.code} 从 ${chart.firstTime} 到 ${chart.lastTime} 的次日走势`}>
      <line className="review-chart-gridline" x1="12" x2={chart.width - 12} y1="12" y2="12" />
      <line className="review-chart-gridline" x1="12" x2={chart.width - 12} y1="80" y2="80" />
      <line className="review-chart-gridline" x1="12" x2={chart.width - 12} y1="148" y2="148" />
      {chart.markers.map((marker, index) => <g className={`review-chart-marker marker-${index}`} key={marker.label}>
        <line x1="12" x2={chart.width - 12} y1={marker.y} y2={marker.y} />
        <text x={chart.width - 12} y={Math.max(marker.y - 3, 10)} textAnchor="end">{marker.label} {formatPrice(marker.price)}</text>
      </g>)}
      <polyline className="review-chart-line" points={chart.polyline} />
      <circle className="review-chart-last" cx={chart.points.at(-1).x} cy={chart.points.at(-1).y} r="3" />
      <text className="review-chart-axis" x="12" y="170">{chart.firstTime.slice(0, 2)}:{chart.firstTime.slice(2)}</text>
      <text className="review-chart-axis" x={chart.width - 12} y="170" textAnchor="end">{chart.lastTime.slice(0, 2)}:{chart.lastTime.slice(2)}</text>
    </svg>
  </section>
}

function T1ReviewPanel({ review, error }) {
  const rows = review?.reviews || []
  return <section id="backtest" className="t1-review-panel" aria-label="昨日推荐复盘">
    <div className="section-heading">
      <div>
        <h2>昨日推荐复盘</h2>
        <span>{review?.review_date ? `复盘日 ${historyDate(review.review_date)}` : '等待首个次日复盘结果'}</span>
      </div>
    </div>
    <p className="review-note">规则退出只按次日上午 09:30–10:30 的固定纪律计算；图表单独展示次日截至 14:50 的真实分时走势，便于对照当日实际波动。</p>
    {!error && rows.length ? <div className="review-chart-grid">{rows.map(({ recommendation_at: recommendationAt, trade }) => <T1MarketChart key={`chart-${recommendationAt}-${trade.code}`} trade={trade} />)}</div> : null}
    {error ? <p className="review-empty">复盘数据暂不可用：{error}</p>
      : rows.length ? <div className="table-wrap review-table-wrap"><table className="t1-review-table">
        <thead><tr><th>推荐日</th><th>股票</th><th>次日上午区间</th><th>规则退出</th></tr></thead>
        <tbody>{rows.map(({ recommendation_at: recommendationAt, trade }) => {
          const hasRange = trade.session_low_price != null && trade.session_high_price != null
          const lowPct = hasRange ? (trade.session_low_price / trade.entry_price - 1) * 100 : null
          const highPct = hasRange ? (trade.session_high_price / trade.entry_price - 1) * 100 : null
          return <tr key={`${recommendationAt}-${trade.code}`}>
            <td>{historyDate(recommendationAt)}</td>
            <td><strong>{trade.code} {trade.name}</strong><small>信号参考价 {formatPrice(trade.entry_price)}</small></td>
            <td>{hasRange ? <><strong>{formatPrice(trade.session_low_price)} – {formatPrice(trade.session_high_price)}</strong><small>{formatPercent(lowPct)} 至 {formatPercent(highPct)}</small></> : <span className="review-pending">区间待积累</span>}</td>
            <td><strong>{formatPrice(trade.exit_price)}</strong><small>{exitReasonLabel[trade.exit_reason] || trade.exit_reason}</small></td>
          </tr>
        })}</tbody>
      </table></div> : <p className="review-empty">尚无已完成的 T+1 复盘。正式推荐后的下一个交易日 10:35 会自动补齐。</p>}
  </section>
}

function SignalDetails({ signal, definition }) {
  return <div className="signal-details">
    <div className="signal-details-heading">
      <div>
        <span>信号详情</span>
        <strong>{signal.code} {signal.name}</strong>
      </div>
      <p>评分 {signal.score} · 风险 {riskLabel[signal.risk_level]}</p>
    </div>
    <div className="signal-detail-factors">
      {(signal.factors || []).map((factor) => <div className="signal-detail-factor" key={factor.key}>
        <span>{factor.label}</span>
        <strong>{factor.value}<em>+{factor.score}</em></strong>
        <small>{factor.description}</small>
      </div>)}
    </div>
    <p className="rule-note">{definition?.risk_rule}</p>
  </div>
}

function IntradayAlertPanel({ alertRun }) {
  const alerts = alertRun?.signals || []
  return <section className="intraday-alert-panel" aria-label="盘中涨停伏击预警">
    <div className="section-heading">
      <div>
        <h2>盘中涨停伏击预警</h2>
        <span>{alertRun ? `最近扫描 ${formatTime(alertRun.observed_at)}` : '等待交易日盘中扫描'}</span>
      </div>
      <span className="alert-frequency">交易日每 2 分钟</span>
    </div>
    <p className="alert-note">按对应交易板归一化涨停进度，并要求最近 3 个两分钟快照连续增强确认；仅作观察预警，不自动交易、不承诺涨停。</p>
    {alerts.length ? <div className="table-wrap"><table className="alert-table latest-alert-table">
      <thead><tr><th>股票</th><th>评分</th><th>涨停进度</th><th>行业平均</th><th>量比</th><th>换手率</th></tr></thead>
      <tbody>{alerts.map((signal) => {
        const value = (key) => signal.factors?.find((factor) => factor.key === key)?.value ?? '—'
        return <tr key={signal.code}>
          <td><strong>{signal.code} {signal.name}</strong><small>{signal.reason}</small></td>
          <td className="score">{signal.score}</td><td>{value('stock_strength')}%</td>
          <td>{value('sector_average')}%</td><td>{value('volume_ratio')}</td><td>{value('turnover')}%</td>
        </tr>
      })}</tbody>
    </table></div> : <p className="alert-empty">{alertRun ? '最近一次扫描未发现满足全部条件的预警对象。' : '预警服务将在下个交易日 09:35 开始扫描。'}</p>}
    <AlertHistoryPanel />
  </section>
}

function AlertTimeline({ event }) {
  const points = event.timeline ?? EMPTY_POINTS
  const chart = useMemo(() => {
    if (!points.length) return null
    const width = 760
    const height = 126
    const xPad = 18
    const yPad = 18
    const values = points.map((point) => point.pct_change)
    const low = Math.min(...values)
    const high = Math.max(...values)
    const span = Math.max(high - low, 0.5)
    const positioned = points.map((point, index) => ({
      ...point,
      x: xPad + (points.length === 1 ? 0 : index / (points.length - 1)) * (width - xPad * 2),
      y: yPad + (high - point.pct_change) / span * (height - yPad * 2),
    }))
    return {
      width,
      height,
      low,
      high,
      positioned,
      polyline: positioned.map((point) => `${point.x},${point.y}`).join(' '),
    }
  }, [points])

  if (!chart) return <p className="alert-timeline-empty">该历史记录只有聚合结果，没有可用的 2 分钟轨迹。</p>
  return <div className="alert-timeline">
    <div className="alert-timeline-head">
      <span>预警后 2 分钟轨迹</span>
      <span>蓝线：涨幅走势 · 橙点：策略命中</span>
    </div>
    <svg viewBox={`0 0 ${chart.width} ${chart.height}`} role="img" aria-label={`${event.code} 预警后涨幅时间线`}>
      <line x1="18" x2={chart.width - 18} y1="18" y2="18" />
      <line x1="18" x2={chart.width - 18} y1={chart.height - 18} y2={chart.height - 18} />
      <polyline points={chart.polyline} />
      {chart.positioned.map((point) => point.is_alert ? <circle
        key={point.observed_at} cx={point.x} cy={point.y} r="4"
      /> : null)}
      <text x="20" y="14">{formatPercent(chart.high)}</text>
      <text x="20" y={chart.height - 4}>{formatPercent(chart.low)}</text>
      <text x={chart.width - 18} y={chart.height - 4} textAnchor="end">
        {historyClock(points.at(-1).observed_at)}
      </text>
    </svg>
  </div>
}

function AlertPriceMove({ event }) {
  const move = relativeAlertMove(event.first_alert_price, event.latest_price)
  if (!move) return <small>最新价待更新</small>

  const arrow = move.direction === 'up' ? '↑' : move.direction === 'down' ? '↓' : '—'
  return <small
    className={`alert-price-move ${move.direction}`}
    aria-label={`最新价 ${formatPrice(event.latest_price)}，相对首次预警${formatPercent(move.percent)}`}
  >
    最新 {formatPrice(event.latest_price)} · {arrow} {formatPercent(move.percent)}
  </small>
}

function SortableAlertHeader({ label, field, sortBy, onSort }) {
  const direction = sortBy === `${field}_asc` ? 'asc' : sortBy === `${field}_desc` ? 'desc' : null
  const nextSort = direction === 'desc' ? `${field}_asc` : `${field}_desc`
  const directionLabel = direction === 'asc' ? '低到高' : direction === 'desc' ? '高到低' : '未排序'

  return <th aria-sort={direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'}>
    <button type="button" className="alert-sort-header" onClick={() => onSort(nextSort)}
      aria-label={`${label}排序，当前${directionLabel}`} title={`点击按${direction === 'desc' ? '低到高' : '高到低'}排序`}>
      <span>{label}</span>
      <span className="sort-triangles" aria-hidden="true">
        <span className="sort-triangle up" data-active={direction === 'asc'}>▲</span>
        <span className="sort-triangle down" data-active={direction === 'desc'}>▼</span>
      </span>
    </button>
  </th>
}

function AlertHistoryPanel() {
  const [filters, setFilters] = useState({ date: '', result: '', persistentOnly: false })
  const [sortBy, setSortBy] = useState('default')
  const [history, setHistory] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandedCode, setExpandedCode] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    const params = {}
    if (filters.date) params.date = filters.date
    if (filters.result) params.result = filters.result
    if (filters.persistentOnly) params.persistent_only = true
    setLoading(true)
    setError(null)
    loadAlertHistory(params, { signal: controller.signal })
      .then((payload) => setHistory(payload))
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setError(requestError.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [filters.date, filters.result, filters.persistentOnly])

  const events = history?.events ?? []
  const sortedEvents = useMemo(() => sortAlertEvents(events, sortBy), [events, sortBy])
  const selectedDate = filters.date || history?.alert_date || ''
  const strengtheningCounts = history?.count_semantics === 'strengthening'
  const mixedCounts = history?.count_semantics === 'mixed'
  const countLabel = strengtheningCounts ? '连续增强次数' : (mixedCounts ? '命中/增强次数' : '命中次数')
  const persistentLabel = strengtheningCounts ? '持续增强' : (mixedCounts ? '持续命中/增强' : '持续预警')
  return <div className="alert-history-panel">
    <div className="alert-history-head">
      <div>
        <span className="eyebrow">盘中预警归档</span>
        <h3>预警历史复盘</h3>
        <p>同一股票的重复命中已合并；最新价相对首次预警价按红涨绿跌显示，持平为灰色。</p>
      </div>
      <div className="alert-history-filters">
        <select aria-label="预警历史日期" value={selectedDate}
          onChange={(event) => setFilters((current) => ({ ...current, date: event.target.value }))}>
          {!selectedDate ? <option value="">暂无日期</option> : null}
          {(history?.available_dates ?? []).map((date) => <option value={date} key={date}>{date}</option>)}
        </select>
        <select aria-label="预警结果" value={filters.result}
          onChange={(event) => setFilters((current) => ({ ...current, result: event.target.value }))}>
          <option value="">全部结果</option>
          <option value="hit_limit">触及涨停</option>
          <option value="not_hit">未触及</option>
          <option value="watching">跟踪中</option>
        </select>
        <select aria-label="预警历史排序" value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
          <option value="default">默认排序</option>
          <option value="hit_count_desc">{countLabel}：高到低</option>
          <option value="hit_count_asc">{countLabel}：低到高</option>
          <option value="max_score_desc">最高评分：高到低</option>
          <option value="max_score_asc">最高评分：低到高</option>
          <option value="first_alert_pct_desc">首次涨幅：高到低</option>
          <option value="first_alert_pct_asc">首次涨幅：低到高</option>
          <option value="max_pct_desc">预警后最高：高到低</option>
          <option value="max_pct_asc">预警后最高：低到高</option>
        </select>
        <button type="button" className={filters.persistentOnly ? 'active' : ''}
          aria-pressed={filters.persistentOnly}
          onClick={() => setFilters((current) => ({ ...current, persistentOnly: !current.persistentOnly }))}>
          仅{persistentLabel}
        </button>
      </div>
    </div>

    <div className="alert-kpis" aria-label="预警历史指标">
      <div title="当日实际执行的 2 分钟扫描次数"><span>扫描次数</span><strong>{history?.scan_count ?? '—'}</strong></div>
      <div title="当日去重后的预警股票数量"><span>预警股票</span><strong>{history?.unique_stock_count ?? '—'}</strong></div>
      <div title={strengtheningCounts ? '同一股票至少连续增强 3 次' : '同一股票至少命中 3 次，约持续 6 分钟'}><span>{persistentLabel}</span><strong>{history?.persistent_count ?? '—'}</strong></div>
      <div title="预警后触及对应交易板涨停阈值"><span>触及涨停</span><strong>{history ? `${history.hit_limit_count} / ${history.hit_limit_rate}%` : '—'}</strong></div>
    </div>

    {error ? <p className="alert-history-empty">预警历史暂不可用：{error}</p>
      : loading && !history ? <p className="alert-history-empty">正在读取预警历史…</p>
        : events.length ? <div className="table-wrap alert-history-table-wrap"><table className="alert-history-table">
          <thead><tr><th>股票</th><th>首次 / 末次</th>
            <SortableAlertHeader label={countLabel} field="hit_count" sortBy={sortBy} onSort={setSortBy} />
            <SortableAlertHeader label="最高评分" field="max_score" sortBy={sortBy} onSort={setSortBy} />
            <SortableAlertHeader label="首次涨幅" field="first_alert_pct" sortBy={sortBy} onSort={setSortBy} />
            <SortableAlertHeader label="预警后最高" field="max_pct" sortBy={sortBy} onSort={setSortBy} />
            <th>结果</th></tr></thead>
          <tbody>{sortedEvents.map((event) => <Fragment key={`${history.alert_date}-${event.code}`}>
            <tr className={expandedCode === event.code ? 'expanded' : undefined}
              aria-expanded={expandedCode === event.code}
              onClick={() => setExpandedCode((current) => current === event.code ? null : event.code)}>
              <td><strong>{event.code} {event.name}</strong><small>首次价 {formatPrice(event.first_alert_price)}</small><AlertPriceMove event={event} /></td>
              <td><strong>{historyClock(event.first_alert_at)} / {historyClock(event.last_alert_at)}</strong><small>跟踪至 {historyClock(event.last_observed_at)}</small></td>
              <td><strong>{event.hit_count}</strong><small>{event.hit_count >= 3 ? persistentLabel : (strengtheningCounts ? '单次增强' : '短时命中')}</small></td>
              <td className="score">{event.max_score}</td>
              <td>{formatPercent(event.first_alert_pct)}</td>
              <td><strong>{formatPercent(event.max_pct)}</strong><small>相对预警价最高 {formatPercent(event.max_gain_from_alert_pct)} · 最大回撤 {formatPercent(event.max_drawdown_from_alert_pct)}</small></td>
              <td><span className={`alert-result ${event.status}`}>{ALERT_RESULT_LABEL[event.status] || event.status}</span></td>
            </tr>
            {expandedCode === event.code ? <tr className="alert-timeline-row">
              <td colSpan="7"><AlertTimeline event={event} /></td>
            </tr> : null}
          </Fragment>)}</tbody>
        </table></div>
          : <p className="alert-history-empty">这个日期还没有命中过预警；扫描次数仍会保留，用于区分“正常空结果”和“任务未执行”。</p>}
  </div>
}

function HistoryPanel({ activeRunId, onOpenRun }) {
  const [filters, setFilters] = useState({ dateFrom: '', dateTo: '' })
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()
    const params = {}
    if (filters.dateFrom) params.date_from = filters.dateFrom
    if (filters.dateTo) params.date_to = filters.dateTo
    const fetcher = loadHistory(PRIMARY_STRATEGY_ID, params, { signal: controller.signal })

    setLoading(true)
    setError(null)
    fetcher
      .then((data) => setRows(data.runs || []))
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') setError(requestError.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [filters])

  const dailyRows = useMemo(() => dailyHistoryRows(rows), [rows])

  return <section className="history-panel" aria-label="历史推荐快照">
    <div className="history-head">
      <div>
        <span className="eyebrow">策略归档</span>
        <h2>历史回看</h2>
        <p>每个交易日尾盘的正式自动采集，都可以回到当时的候选、评分和数据来源。</p>
      </div>
      <div className="history-filters">
        <input aria-label="历史起始日期" type="date" value={filters.dateFrom}
          onChange={(event) => setFilters((current) => ({ ...current, dateFrom: event.target.value }))} />
        <span>至</span>
        <input aria-label="历史截止日期" type="date" value={filters.dateTo}
          onChange={(event) => setFilters((current) => ({ ...current, dateTo: event.target.value }))} />
        <button type="button" className="history-reset" disabled={loading}
          onClick={() => setFilters({ dateFrom: '', dateTo: '' })}>重置</button>
      </div>
    </div>

    <div className="history-summary">
      <span>{loading ? '正在更新归档…' : `已找到 ${rows.length} 次正式归档`}</span>
      <span>仅展示实时数据</span>
    </div>
    {error ? <p className="history-empty">{error}</p>
      : !loading && dailyRows.length === 0 ? <p className="history-empty">尚无符合条件的实时归档。尾盘运行策略后会自动出现在这里。</p>
        : <div className="history-table-wrap daily-history-table-wrap">
          <table className="history-table daily-history-table">
            <thead>
              <tr>
                <th scope="col">日期</th>
                <th scope="col">采集时间</th>
                <th scope="col">候选数</th>
                <th scope="col">数据来源</th>
                <th scope="col">状态</th>
                <th scope="col"><span className="sr-only">查看详情</span></th>
              </tr>
            </thead>
            <tbody>
              {dailyRows.map((row) => {
                const isActive = activeRunId === row.run_id
                return <tr key={row.run_id} className={isActive ? 'active' : undefined}>
                  <th scope="row" className="history-date"><time dateTime={row.observed_at}>{historyDate(row.observed_at)}</time></th>
                  <td><time dateTime={row.observed_at}>{historyClock(row.observed_at)}</time></td>
                  <td className="history-candidate-count">{row.signal_count ?? '—'}</td>
                  <td className="history-source" title={row.data_source}>{row.data_source || '未知数据源'}</td>
                  <td><span className="history-status">{HISTORY_STATUS_LABEL[row.execution_status] || row.execution_status}</span></td>
                  <td><button type="button" className="history-open" onClick={() => onOpenRun(row)}>查看</button></td>
                </tr>
              })}
            </tbody>
          </table>
        </div>}
  </section>
}

export default function App() {
  const [page, setPage] = useState(() => window.location.hash === '#review-center' ? 'review' : 'daily')
  useEffect(() => {
    const change = () => setPage(window.location.hash === '#review-center' ? 'review' : 'daily')
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  const [definitions, setDefinitions] = useState([])
  const [activeStrategy, setActiveStrategy] = useState(PRIMARY_STRATEGY_ID)
  const [runs, setRuns] = useState({})
  const [selected, setSelected] = useState(null)
  const [status, setStatus] = useState('正在加载自动归档…')
  const [showConfig, setShowConfig] = useState(null)
  const [t1Review, setT1Review] = useState(null)
  const [t1ReviewError, setT1ReviewError] = useState(null)
  const [alertRun, setAlertRun] = useState(null)

  const [viewingHistorical, setViewingHistorical] = useState(null)
  const signalAreaRef = useRef(null)

  useEffect(() => {
    Promise.all([
      loadStrategy(),
      Promise.all(STRATEGY_TABS.map((tab) => loadLatestForStrategy(tab.id).catch(() => null))),
      loadT1Review(PRIMARY_STRATEGY_ID).catch((error) => ({ error })),
      loadLatestAlert().catch(() => null),
    ])
      .then(([catalog, latestPerStrategy, review, latestAlert]) => {
        setDefinitions(catalog.strategies)
        const runMap = {}
        latestPerStrategy.forEach((run, index) => {
          const tab = STRATEGY_TABS[index]
          if (run) runMap[tab.id] = run
        })
        setRuns(runMap)
        setSelected(runMap[activeStrategy]?.signals?.[0] ?? null)
        if (review.error) setT1ReviewError(review.error.message)
        else setT1Review(review)
        setAlertRun(latestAlert)
        setStatus('已读取最近一次自动归档')
      })
      .catch((error) => setStatus(error.message))
  }, [])

  useEffect(() => {
    if (!viewingHistorical) return
    signalAreaRef.current?.scrollIntoView({ behavior: 'auto', block: 'start' })
  }, [viewingHistorical])

  const activeRun = viewingHistorical?.run || runs[activeStrategy] || null
  const run = activeRun
  const definition = definitions.find((d) => d.id === activeStrategy) || null

  const stats = useMemo(() => ({
    candidates: run?.signals?.length ?? 0,
    universe: run?.universe_size ?? 0,
    observed: formatTime(run?.observed_at),
  }), [run])

  async function openConfig() {
    try {
      const result = await loadStrategyConfig(activeStrategy)
      const def = definitions.find((d) => d.id === activeStrategy)
      setShowConfig({ id: activeStrategy, name: def?.name || activeStrategy, config: result.config })
    } catch (error) {
      setStatus(error.message)
    }
  }

  async function openHistoricalRun(row) {
    try {
      const full = await loadHistoricalRun(row.strategy_id, row.run_id)
      setActiveStrategy(row.strategy_id)
      setSelected(full.signals?.[0] ?? null)
      setViewingHistorical({ run: full, row })
      setStatus(`已加载 ${row.strategy_id} 在 ${formatTime(full.observed_at)} 的历史快照。`)
    } catch (error) {
      setStatus(error.message)
    }
  }

  function backToLatest() {
    const latest = runs[activeStrategy]
    setViewingHistorical(null)
    setSelected(latest?.signals?.[0] ?? null)
    setStatus('已回到最新一次实时快照。')
  }

  function pickStrategy(id) {
    window.location.hash = id
    setPage('daily')
    setActiveStrategy(id)
    setViewingHistorical(null)
    setSelected(runs[id]?.signals?.[0] ?? null)
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand">Signal Forge</div>
      <nav>
        {STRATEGY_TABS.map((tab) => (
          <a key={tab.id} href={`#${tab.id}`} className={page === 'daily' && activeStrategy === tab.id ? 'active' : ''}
             onClick={(e) => { e.preventDefault(); pickStrategy(tab.id) }}>
            <span className="tab-priority">{tab.priority}</span>{tab.label}
          </a>
        ))}
        <a href="#backtest">T+1 回测</a>
        <a href="#review-center" className={page === 'review' ? 'active' : ''}>复盘与诊断</a>
      </nav>
      <div className="sidebar-note">仅研究，不构成投资建议</div>
    </aside>
    <main className="workspace">
      <nav className="page-switch" aria-label="页面导航"><a href="#fishing-reversal" aria-current={page === 'daily' ? 'page' : undefined}>每日信号</a><a href="#review-center" aria-current={page === 'review' ? 'page' : undefined}>复盘与诊断</a></nav>
      {page === 'review' ? <ReviewCenter /> : <>
      {viewingHistorical && <div className="historical-banner" role="status">
        <span>
          正在查看历史快照 ·
          <strong>{viewingHistorical.row.strategy_id}</strong>
          · {formatTime(viewingHistorical.run.observed_at)} ·
          <em>{viewingHistorical.row.signal_count} 候选 · {viewingHistorical.row.universe_size} 扫描</em>
        </span>
        <button onClick={backToLatest}>回到最新</button>
      </div>}
      <header className="topbar">
        <span>研究快照</span>
        <strong>{stats.observed}</strong>
        <span className="dot" />
        <span>{run ? (run.execution_status === 'tradable' ? '自动归档 · 可执行时段' : '自动归档 · 非可执行时段') : '等待下次自动归档'}</span>
        <span className="source-tag">{run?.data_source ?? '等待数据源'}</span>
      </header>
      <section className="headline">
        <div>
          <h1>{definition?.name ?? '尾盘恐慌止跌'} <span>· {definition?.version ?? 'V1'}</span></h1>
          <p>{definition?.summary ?? '加载中'}</p>
        </div>
        <div className="actions">
          <p className="automation-note"><strong>自动采集</strong><span>交易日 14:50 生成正式快照</span></p>
          <button className="ghost" onClick={openConfig}>参数调优</button>
        </div>
      </section>
      <p className="risk-copy">风险提示：策略只生成可研究的候选，不能保证次日盈利；隔夜跳空可能使风险线失效。</p>
      <p className="status-line" role="status">{status}</p>

      <section className="summary-strip">
        <div><span>候选信号</span><strong>{stats.candidates}</strong></div>
        <div><span>扫描范围</span><strong>{stats.universe || '—'}</strong></div>
        <div><span>执行时段</span><strong>{definition?.execution_window ?? '14:30–15:00'}</strong></div>
      </section>

      <section id="recommendations" ref={signalAreaRef} className="content-grid">
        <div className="signal-area">
          <div className="section-heading">
            <h2>{definition?.name ?? '候选池'}</h2>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>排名</th><th>股票</th><th>评分</th><th>关键因子</th><th>风险</th></tr></thead>
            <tbody>
              {run?.signals?.length ? run.signals.map((signal, index) => <Fragment key={signal.code}>
                <tr onClick={() => setSelected(signal)} className={selected?.code === signal.code ? 'selected-row' : ''} aria-expanded={selected?.code === signal.code}>
                  <td>{index + 1}</td>
                  <td><strong>{signal.code} {signal.name}</strong><small>{signal.reason}</small></td>
                  <td className="score">{signal.score}</td>
                  <td>{(signal.factors || []).slice(0, 2).map((f) => `${f.label} ${f.value}`).join(' / ')}</td>
                  <td className={`risk ${signal.risk_level}`}>{riskLabel[signal.risk_level]}</td>
                </tr>
                {selected?.code === signal.code && <tr className="signal-details-row">
                  <td colSpan="5"><SignalDetails signal={signal} definition={definition} /></td>
                </tr>}
              </Fragment>) : <tr><td colSpan="5" className="empty">本次快照未筛出 V1 候选，可在下次自动采集后再查看。</td></tr>}
            </tbody>
          </table></div>
        </div>
      </section>

      <IntradayAlertPanel alertRun={alertRun} />

      <T1ReviewPanel review={t1Review} error={t1ReviewError} />

      <HistoryPanel
        activeRunId={viewingHistorical?.row.run_id}
        onOpenRun={openHistoricalRun}
      />
      </>}

    </main>
    {showConfig && <div className="drawer-overlay" onClick={() => setShowConfig(null)}>
      <div onClick={(e) => e.stopPropagation()}>
        <ConfigDrawer strategy={showConfig} onClose={() => setShowConfig(null)} />
      </div>
    </div>}
  </div>
}
