export function metricView(metric) {
  return {
    value: Number.isFinite(metric?.rate_pct) ? `${metric.rate_pct.toFixed(1)}%` : '未知',
    denominator: `${metric?.success_count ?? '—'} / ${metric?.eligible_count ?? '—'}`,
    unknown: metric?.unknown_count ?? '—',
    coverage: Number.isFinite(metric?.coverage_pct) ? `${metric.coverage_pct.toFixed(1)}%` : '未知',
  }
}

export function defaultReviewRange(now = new Date()) {
  return reviewPresetRange(7, now)
}

export function reviewPresetRange(days, now = new Date()) {
  const shanghai = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
  const end = new Date(`${shanghai}T00:00:00Z`)
  end.setUTCDate(end.getUTCDate() - 1)
  const start = new Date(end)
  start.setUTCDate(start.getUTCDate() - (days - 1))
  return { date_from: start.toISOString().slice(0, 10), date_to: end.toISOString().slice(0, 10) }
}

export function latestMarketObservation(report) {
  let latest = null
  for (const event of report.events || []) {
    const times = [event.last_observed_at]
    if (!event.closing_evidence?.conflict) times.push(event.closing_evidence?.quote?.price_at)
    const nextClose = event.next_day_close?.closing_evidence
    if (nextClose && !nextClose.conflict) times.push(nextClose.quote?.price_at)
    for (const time of times) {
      const timestamp = time ? reviewTimestamp(time) : null
      if (timestamp != null && (latest == null || timestamp > latest)) latest = timestamp
    }
  }
  return latest
}

export function validateReviewRange(start, end) {
  const valid = value => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
  if (!valid(start) || !valid(end)) return '请选择有效的起止日期。'
  if (start < '1900-01-01' || end > '9998-12-31' || start > end || (Date.parse(end) - Date.parse(start)) / 86400000 > 365) return '日期须有序，且范围不超过366天。'
  return ''
}

export function sortReviewEvents(events, field, direction) {
  return [...events].sort((a, b) => {
    const x = field === 'first_at' && a[field] ? reviewTimestamp(a[field]) : a[field]
    const y = field === 'first_at' && b[field] ? reviewTimestamp(b[field]) : b[field]
    if (x == null) return y == null ? 0 : 1
    if (y == null) return -1
    const delta = typeof x === 'number' ? x - y : String(x).localeCompare(String(y))
    return direction === 'asc' ? delta : -delta
  })
}

export function reviewTimestamp(value) {
  const timestamp = Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}+08:00`)
  return Number.isFinite(timestamp) ? timestamp : null
}

export function issueGroups(events) {
  const counts = new Map()
  for (const event of events) for (const flag of new Set(event.quality_flags || [])) counts.set(flag, (counts.get(flag) || 0) + 1)
  return [...counts].map(([flag, count]) => ({ flag, count })).sort((a, b) => b.count - a.count || a.flag.localeCompare(b.flag))
}

export const FLAG_LABELS = {
  close_unverified: '缺少收盘证据', closing_source_conflict: '收盘来源冲突', limit_price_unknown: '真实涨停价未知',
  touch_order_unknown: '触板先后顺序未知', publication_time_unknown: '发布时间未留档', configuration_snapshot_unknown: '参数快照未留档',
  invalid_first_price: '首次价格无效', invalid_last_price: '末次价格无效', no_post_alert_observation: '无后续观测',
  mixed_strategy_versions: '同日混合策略版本', signal_not_before_close: '信号不早于收盘',
}
export const STRATEGY_NAMES = { 'fishing-reversal': 'V1 · 尾盘恐慌止跌', 'limit-up-ambush': '盘中涨停伏击' }
