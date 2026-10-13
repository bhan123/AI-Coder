import assert from 'node:assert/strict'
import test from 'node:test'

import { PRIMARY_STRATEGY_ID, VISIBLE_STRATEGY_TABS } from './strategy-tabs.js'

test('the frontend currently exposes V1 as its only strategy', () => {
  assert.equal(PRIMARY_STRATEGY_ID, 'fishing-reversal')
  assert.deepEqual(VISIBLE_STRATEGY_TABS.map((strategy) => strategy.id), ['fishing-reversal'])
  assert.equal(VISIBLE_STRATEGY_TABS[0].priority, 'V1')
})
