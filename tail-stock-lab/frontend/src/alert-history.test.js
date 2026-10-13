import assert from 'node:assert/strict'
import test from 'node:test'

import { relativeAlertMove, sortAlertEvents } from './alert-history.js'

test('relative alert move marks a latest price above the first alert as up', () => {
  assert.deepEqual(relativeAlertMove(10, 10.5), {
    direction: 'up',
    percent: 5,
  })
})

test('relative alert move distinguishes down, flat, and unavailable prices', () => {
  assert.deepEqual(relativeAlertMove(20, 19), { direction: 'down', percent: -5 })
  assert.deepEqual(relativeAlertMove(20, 20), { direction: 'flat', percent: 0 })
  assert.equal(relativeAlertMove(0, 20), null)
  assert.equal(relativeAlertMove(20, null), null)
})

test('alert history can sort by hit count without mutating the API order', () => {
  const events = [
    { code: '000001', hit_count: 2, max_score: 91 },
    { code: '000002', hit_count: 8, max_score: 82 },
    { code: '000003', hit_count: 4, max_score: 88 },
  ]

  assert.deepEqual(
    sortAlertEvents(events, 'hit_count_desc').map((event) => event.code),
    ['000002', '000003', '000001'],
  )
  assert.deepEqual(events.map((event) => event.code), ['000001', '000002', '000003'])
})

test('alert history supports ascending and descending score and hit-count orders', () => {
  const events = [
    { code: '000001', hit_count: 2, max_score: 91 },
    { code: '000002', hit_count: 8, max_score: 82 },
    { code: '000003', hit_count: 4, max_score: 88 },
  ]

  assert.deepEqual(sortAlertEvents(events, 'hit_count_asc').map((event) => event.code), ['000001', '000003', '000002'])
  assert.deepEqual(sortAlertEvents(events, 'max_score_desc').map((event) => event.code), ['000001', '000003', '000002'])
  assert.deepEqual(sortAlertEvents(events, 'max_score_asc').map((event) => event.code), ['000002', '000003', '000001'])
})

test('alert history sortable table also orders first gain and post-alert high', () => {
  const events = [
    { code: '000001', first_alert_pct: 7.2, max_pct: 8.1 },
    { code: '000002', first_alert_pct: 9.1, max_pct: 9.5 },
    { code: '000003', first_alert_pct: 8.4, max_pct: 8.8 },
  ]

  assert.deepEqual(sortAlertEvents(events, 'first_alert_pct_asc').map((event) => event.code), ['000001', '000003', '000002'])
  assert.deepEqual(sortAlertEvents(events, 'max_pct_desc').map((event) => event.code), ['000002', '000003', '000001'])
})
