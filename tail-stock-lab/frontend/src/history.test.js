import assert from 'node:assert/strict'
import test from 'node:test'

import { dailyHistoryRows, groupHistoryRows, sortHistoryRows } from './history.js'

test('V1 is always first within each day of formal history', () => {
  const rows = sortHistoryRows([
    { strategy_id: 'p3-platform-breakout', observed_at: '2026-08-11T14:50:01+08:00' },
    { strategy_id: 'p1-sector-resonance', observed_at: '2026-08-11T14:50:01+08:00' },
    { strategy_id: 'fishing-reversal', observed_at: '2026-08-11T14:50:01+08:00' },
    { strategy_id: 'p4-leader-reconvergence', observed_at: '2026-08-10T14:50:01+08:00' },
    { strategy_id: 'fishing-reversal', observed_at: '2026-08-10T14:50:01+08:00' },
  ])

  assert.deepEqual(rows.map((row) => row.strategy_id), [
    'fishing-reversal', 'p1-sector-resonance', 'p3-platform-breakout',
    'fishing-reversal', 'p4-leader-reconvergence',
  ])
})

test('history table groups formal runs by day while preserving V1 first', () => {
  const groups = groupHistoryRows([
    { run_id: 'p1-latest', strategy_id: 'p1-sector-resonance', observed_at: '2026-08-11T14:50:01+08:00' },
    { run_id: 'v1-prior', strategy_id: 'fishing-reversal', observed_at: '2026-08-10T14:50:01+08:00' },
    { run_id: 'v1-latest', strategy_id: 'fishing-reversal', observed_at: '2026-08-11T14:50:01+08:00' },
  ])

  assert.deepEqual(groups.map((group) => group.key), ['2026-08-11', '2026-08-10'])
  assert.deepEqual(groups[0].rows.map((row) => row.run_id), ['v1-latest', 'p1-latest'])
})

test('daily history table keeps one dated row for each formal run', () => {
  const rows = dailyHistoryRows([
    { run_id: 'older', strategy_id: 'fishing-reversal', observed_at: '2026-08-10T14:50:01+08:00' },
    { run_id: 'latest', strategy_id: 'fishing-reversal', observed_at: '2026-08-11T14:50:01+08:00' },
  ])

  assert.deepEqual(rows.map((row) => [row.day_key, row.run_id]), [
    ['2026-08-11', 'latest'],
    ['2026-08-10', 'older'],
  ])
})
