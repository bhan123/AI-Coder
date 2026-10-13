import test from 'node:test'
import assert from 'node:assert/strict'
import { loadReviewCollectionJobs, loadReviewCollectionAttempts } from './api.js'

test('collection requests preserve exact filters and abort signal and remain read-only', async t => {
  const calls = []
  t.mock.method(globalThis, 'fetch', async (path, options) => {
    calls.push({ path, options })
    return { ok: true, json: async () => ({ items: [], total: 0 }) }
  })
  const signal = new AbortController().signal
  await loadReviewCollectionJobs({ date_from: '2026-09-01', date_to: '2026-09-09', status: '', code: '000001', offset: 25, limit: 25 }, { signal })
  await loadReviewCollectionAttempts({ trade_date: '2026-09-04', code: '000001', provider: 'source / one', limit: 25 }, { signal })
  const jobs = new URL(calls[0].path, 'https://example.test')
  assert.equal(jobs.pathname, '/api/review/collection/jobs')
  assert.equal(jobs.searchParams.get('offset'), '25')
  assert.equal(jobs.searchParams.get('code'), '000001')
  assert.equal(jobs.searchParams.has('status'), false)
  const attempts = new URL(calls[1].path, 'https://example.test')
  assert.equal(attempts.pathname, '/api/review/collection/attempts')
  assert.equal(attempts.searchParams.get('provider'), 'source / one')
  assert.ok(calls.every(call => call.options.signal === signal && !call.options.method))
})

test('queue filters use target dates and never infer a strategy or mutate the applied range', async () => {
  const { collectionQuery } = await import('./review-collection.js')
  const range = { strategy_id: 'fishing-reversal', date_from: '2026-09-01', date_to: '2026-09-09' }
  assert.deepEqual(collectionQuery(range, { code: ' 000001 ', status: 'failed', offset: 25 }), {
    date_from: '2026-09-01', date_to: '2026-09-09', code: '000001', status: 'failed', offset: 25, limit: 25,
  })
  assert.equal(range.strategy_id, 'fishing-reversal')
  assert.throws(() => collectionQuery(range, { code: '001' }), /六位/)
  assert.throws(() => collectionQuery(range, { status: 'invalid' }), /状态/)
  assert.throws(() => collectionQuery({ ...range, date_to: '2026-08-31' }), /日期/)
})

test('missing or mismatched queue responses cannot masquerade as an empty successful page', async () => {
  const { collectionPageError } = await import('./review-collection.js')
  const empty = { queue_status: 'not_initialized', items: [], total: 0, offset: 0, limit: 25, next_offset: null, counts_by_status: {} }
  assert.equal(collectionPageError(empty), '')
  for (const value of [null, {}, { ...empty, total: '0' }, { ...empty, queue_status: 'available', total: 4 }, { ...empty, next_offset: 0 }]) {
    assert.ok(collectionPageError(value))
  }
  const attempt = { sequence: 1, trade_date: '2026-09-04', code: '000001', provider: 'source', status: 'failed', attempted_at: '2026-09-04T16:00:00+08:00' }
  const page = { queue_status: 'available', items: [attempt], total: 2, offset: 0, limit: 1, next_offset: 1 }
  assert.equal(collectionPageError(page, 'attempts'), '')
  assert.ok(collectionPageError({ ...page, next_offset: 0 }, 'attempts'))
})

test('queue status explains collection readiness without claiming evidence completeness', async () => {
  const { collectionAvailability } = await import('./review-collection.js')
  const complete = collectionAvailability({ availability: 'completed' })
  assert.match(complete.label, /采集/)
  assert.match(complete.note, /不代表/)
  assert.equal(collectionAvailability({ availability: 'cooldown' }).label, '失败冷却中')
  assert.equal(collectionAvailability({ availability: 'lease_expired', ready_to_collect: true }).label, '租约过期，待接续')
  assert.equal(collectionAvailability({ availability: 'ready', ready_to_collect: false }).label, '状态待核查')
  assert.equal(collectionAvailability({ availability: 'new-unknown' }).label, '状态待核查')
})
