import assert from 'node:assert/strict'
import test from 'node:test'

import { loadAlertHistory, loadAllHistory, loadHistoricalRun, loadHistory, loadLatestAlert, loadT1Review, runStrategy } from './api.js'

test('review requests are readonly and support cancellation and report identifiers', async () => {
  const { loadReviewSummary, loadReviewReports, loadReviewReport, loadReviewAutomation } = await import('./api.js')
  const calls = []
  globalThis.fetch = async (path, options) => { calls.push({ path, options }); return { ok: true, json: async () => ({}) } }
  const options = { signal: new AbortController().signal }
  await loadReviewSummary({ strategy_id: 'limit-up-ambush', date_from: '2026-09-01', date_to: '2026-09-07' }, options)
  await loadReviewReports({ strategy_id: 'fishing-reversal', limit: 50 }, options)
  await loadReviewReport('report/a', options)
  await loadReviewAutomation({}, options)
  assert.equal(calls[0].path, '/api/review/summary?strategy_id=limit-up-ambush&date_from=2026-09-01&date_to=2026-09-07')
  assert.equal(calls[1].path, '/api/review/reports?strategy_id=fishing-reversal&limit=50')
  assert.equal(calls[2].path, '/api/review/reports/report%2Fa')
  assert.equal(calls[3].path, '/api/review/automation')
  assert.ok(calls.every(call => call.options.signal === options.signal && !call.options.method))
})

test('runStrategy requests a live snapshot for the currently selected strategy', async () => {
  let requestedPath = null
  globalThis.fetch = async (path) => {
    requestedPath = path
    return { ok: true, json: async () => ({}) }
  }

  await runStrategy('p1-sector-resonance')

  assert.equal(
    requestedPath,
    '/api/strategies/p1-sector-resonance/run?mode=live',
  )
})

test('loadHistory omits empty params and preserves filled ones', async () => {
  let requestedPath = null
  globalThis.fetch = async (path) => {
    requestedPath = path
    return { ok: true, json: async () => ({ runs: [] }) }
  }

  await loadHistory('fishing-reversal', { date_from: '2026-08-01', date_to: '' })
  assert.equal(requestedPath, '/api/strategies/fishing-reversal/history?date_from=2026-08-01')

  await loadAllHistory({ date_from: '2026-08-01', date_to: '2026-08-03' })
  assert.equal(
    requestedPath,
    '/api/strategies/history?date_from=2026-08-01&date_to=2026-08-03',
  )

  await loadHistoricalRun('fishing-reversal', 'run-abc')
  assert.equal(requestedPath, '/api/strategies/fishing-reversal/run/run-abc')
})

test('loadT1Review requests the latest completed review for a strategy', async () => {
  let requestedPath = null
  globalThis.fetch = async (path) => {
    requestedPath = path
    return { ok: true, json: async () => ({ reviews: [] }) }
  }

  await loadT1Review('fishing-reversal')

  assert.equal(requestedPath, '/api/strategies/fishing-reversal/t1-review/latest')
})

test('loadLatestAlert requests the independent intraday alert feed', async () => {
  let requestedPath = null
  globalThis.fetch = async (path) => {
    requestedPath = path
    return { ok: true, json: async () => ({}) }
  }

  await loadLatestAlert()

  assert.equal(requestedPath, '/api/strategies/limit-up-ambush/latest')
})

test('loadAlertHistory requests the deduplicated alert event view with filters', async () => {
  let requestedPath = null
  globalThis.fetch = async (path) => {
    requestedPath = path
    return { ok: true, json: async () => ({ events: [] }) }
  }

  await loadAlertHistory({ date: '2026-08-13', result: 'hit_limit', persistent_only: true })

  assert.equal(
    requestedPath,
    '/api/strategies/limit-up-ambush/alert-history?date=2026-08-13&result=hit_limit&persistent_only=true',
  )
})
