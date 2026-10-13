const STRATEGY_ORDER = {
  'fishing-reversal': 0,
  'p1-sector-resonance': 1,
  'p2-trend-pullback': 2,
  'p3-platform-breakout': 3,
  'p4-leader-reconvergence': 4,
}

export function sortHistoryRows(rows) {
  return [...rows].sort((left, right) => {
    const leftDay = String(left.observed_at || '').slice(0, 10)
    const rightDay = String(right.observed_at || '').slice(0, 10)
    if (leftDay !== rightDay) return rightDay.localeCompare(leftDay)

    const leftOrder = STRATEGY_ORDER[left.strategy_id] ?? Number.MAX_SAFE_INTEGER
    const rightOrder = STRATEGY_ORDER[right.strategy_id] ?? Number.MAX_SAFE_INTEGER
    if (leftOrder !== rightOrder) return leftOrder - rightOrder
    return String(right.observed_at || '').localeCompare(String(left.observed_at || ''))
  })
}

export function groupHistoryRows(rows) {
  return sortHistoryRows(rows).reduce((groups, row) => {
    const key = String(row.observed_at || '').slice(0, 10)
    const previous = groups[groups.length - 1]
    if (previous?.key === key) previous.rows.push(row)
    else groups.push({ key, rows: [row] })
    return groups
  }, [])
}

export function dailyHistoryRows(rows) {
  return sortHistoryRows(rows).map((row) => ({
    ...row,
    day_key: String(row.observed_at || '').slice(0, 10),
  }))
}
