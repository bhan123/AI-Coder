export async function request(path, options) {
  const response = await fetch(path, options)
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    throw new Error(payload.detail || '服务暂不可用')
  }
  return response.json()
}

export const loadStrategy = () => request('/api/strategies')
export const loadLatest = () => request('/api/strategies/fishing-reversal/latest')
export const runStrategy = (sid) => request(`/api/strategies/${sid}/run?mode=live`, { method: 'POST' })
export const runAllStrategies = () => request('/api/strategies/run-all?mode=live', { method: 'POST' })
export const loadLatestForStrategy = (sid) => request(`/api/strategies/${sid}/latest`)
export const loadLatestAlert = () => loadLatestForStrategy('limit-up-ambush')
export const loadReviewSummary = (params, options) => request(withParams('/api/review/summary', params), options)
export const loadReviewReports = (params, options) => request(withParams('/api/review/reports', params), options)
export const loadReviewReport = (id, options) => request(`/api/review/reports/${encodeURIComponent(id)}`, options)
export const loadReviewAutomation = (_params, options) => request('/api/review/automation', options)
export const loadReviewCollectionJobs = (params, options) => request(withParams('/api/review/collection/jobs', params), options)
export const loadReviewCollectionAttempts = (params, options) => request(withParams('/api/review/collection/attempts', params), options)
export const loadStrategyConfig = (sid) => request(`/api/strategies/${sid}/config`)
export const saveStrategyConfig = (sid, overrides) => request(`/api/strategies/${sid}/config`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ overrides }),
})

function withParams(path, params = {}) {
  const entries = Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null)
  if (!entries.length) return path
  const qs = new URLSearchParams(entries).toString()
  return `${path}?${qs}`
}

export const loadHistory = (sid, params = {}, options) => request(withParams(`/api/strategies/${sid}/history`, params), options)
export const loadAllHistory = (params = {}, options) => request(withParams('/api/strategies/history', params), options)
export const loadHistoricalRun = (sid, runId) => request(`/api/strategies/${sid}/run/${runId}`)
export const loadT1Review = (sid) => request(`/api/strategies/${sid}/t1-review/latest`)
export const loadAlertHistory = (params = {}, options) => request(
  withParams('/api/strategies/limit-up-ambush/alert-history', params),
  options,
)
