import test from 'node:test'
import assert from 'node:assert/strict'
import { metricView, defaultReviewRange, validateReviewRange, sortReviewEvents, issueGroups, reviewPresetRange, latestMarketObservation } from './review-center.js'

test('review metrics keep unknown distinct from zero and show valid denominators', () => {
  assert.deepEqual(metricView({ rate_pct: null, success_count: 0, eligible_count: 0, unknown_count: 12, coverage_pct: 0 }),
    { value: '未知', denominator: '0 / 0', unknown: 12, coverage: '0.0%' })
  assert.equal(metricView({ rate_pct: 0, success_count: 0, eligible_count: 3, unknown_count: 2, coverage_pct: 60 }).value, '0.0%')
  assert.equal(metricView(undefined).value, '未知')
})

test('review dates use Shanghai previous day and reject invalid or oversized ranges', () => {
  assert.deepEqual(defaultReviewRange(new Date('2026-09-07T17:00:00Z')), { date_from: '2026-09-01', date_to: '2026-09-07' })
  assert.equal(validateReviewRange('2026-09-01', '2026-09-07'), '')
  for (const [start, end] of [['', ''], ['2026-02-30', '2026-03-01'], ['2026-09-08', '2026-09-01'], ['2025-01-01', '2026-09-01']]) {
    assert.ok(validateReviewRange(start, end))
  }
})

test('review sorting is immutable, nulls stay last, and issues count unique affected events', () => {
  const rows = [{ event_id: 'a', first_score: 80, close_return_pct: null, quality_flags: ['close_unverified', 'close_unverified'] },
    { event_id: 'b', first_score: 70, close_return_pct: -2, quality_flags: ['close_unverified'] }]
  assert.deepEqual(sortReviewEvents(rows, 'close_return_pct', 'asc').map(x => x.event_id), ['b', 'a'])
  assert.deepEqual(sortReviewEvents(rows, 'first_score', 'asc').map(x => x.event_id), ['b', 'a'])
  assert.equal(rows[0].event_id, 'a')
  assert.deepEqual(issueGroups(rows), [{ flag: 'close_unverified', count: 2 }])
})

test('chronological sorting respects UTC offsets and Shanghai legacy timestamps', () => {
  const events = [{first_at:'2026-09-04T02:00:00Z'}, {first_at:'2026-09-04T09:00:00+08:00'}, {first_at:'2026-09-04T09:30:00'}]
  assert.deepEqual(sortReviewEvents(events, 'first_at', 'asc'), [events[1], events[2], events[0]])
})

test('quick ranges are explicit calendar days ending yesterday in Shanghai', () => {
  const now = new Date('2026-09-07T17:00:00Z')
  assert.deepEqual(reviewPresetRange(1, now), {date_from:'2026-09-07',date_to:'2026-09-07'})
  assert.deepEqual(reviewPresetRange(30, now), {date_from:'2026-08-09',date_to:'2026-09-07'})
})

test('market freshness uses observed prices, never report generation cutoff', () => {
  assert.equal(latestMarketObservation({as_of:'2026-09-08T18:00:00+08:00', events:[]}), null)
  assert.equal(latestMarketObservation({events:[{last_observed_at:'2026-09-04T14:58:00+08:00',closing_evidence:{quote:{price_at:'2026-09-04T15:00:00+08:00'}}}]}), Date.parse('2026-09-04T15:00:00+08:00'))
})

test('market freshness includes next-day close evidence but excludes conflicts', () => {
  const event={last_observed_at:'2026-09-04T14:50:00+08:00',next_day_close:{closing_evidence:{quote:{price_at:'2026-09-07T15:00:00+08:00'}}}}
  assert.equal(latestMarketObservation({events:[event]}), Date.parse('2026-09-07T15:00:00+08:00'))
  event.next_day_close.closing_evidence.conflict=true
  assert.equal(latestMarketObservation({events:[event]}), Date.parse('2026-09-04T14:50:00+08:00'))
})
