export function relativeAlertMove(firstPrice, latestPrice) {
  if (!Number.isFinite(firstPrice) || firstPrice <= 0 || !Number.isFinite(latestPrice)) return null

  const percent = Math.round((latestPrice / firstPrice - 1) * 1_000_000) / 10_000
  return {
    direction: percent > 0 ? 'up' : percent < 0 ? 'down' : 'flat',
    percent,
  }
}

export function sortAlertEvents(events, sortBy) {
  const sorted = [...events]
  const [field, direction] = {
    hit_count_desc: ['hit_count', 'desc'],
    hit_count_asc: ['hit_count', 'asc'],
    max_score_desc: ['max_score', 'desc'],
    max_score_asc: ['max_score', 'asc'],
    first_alert_pct_desc: ['first_alert_pct', 'desc'],
    first_alert_pct_asc: ['first_alert_pct', 'asc'],
    max_pct_desc: ['max_pct', 'desc'],
    max_pct_asc: ['max_pct', 'asc'],
  }[sortBy] ?? []

  if (!field) return sorted
  const multiplier = direction === 'desc' ? -1 : 1
  sorted.sort((left, right) => multiplier * (left[field] - right[field]))
  return sorted
}
