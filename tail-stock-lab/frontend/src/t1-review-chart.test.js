import assert from 'node:assert/strict'
import test from 'node:test'

import { buildT1Chart } from './t1-review-chart.js'

test('buildT1Chart uses the persisted next-day minute series and keeps price markers', () => {
  const chart = buildT1Chart({
    open_price: 9.7,
    high_price: 10.6,
    low_price: 9.7,
    last_price: 10.5,
    points: [{ time: '0930', price: 9.7 }, { time: '1030', price: 10.1 }, { time: '1450', price: 10.5 }],
  }, [{ label: '推荐价', price: 10 }, { label: '规则退出', price: 9.7 }])

  assert.equal(chart.points.length, 3)
  assert.equal(chart.openPrice, 9.7)
  assert.equal(chart.highPrice, 10.6)
  assert.equal(chart.lastPrice, 10.5)
  assert.deepEqual(chart.markers.map((marker) => marker.label), ['推荐价', '规则退出'])
  assert.match(chart.polyline, /^12,/) 
})

test('buildT1Chart has no chart before a 14:50 market review is archived', () => {
  assert.equal(buildT1Chart(null), null)
  assert.equal(buildT1Chart({ points: [] }), null)
})
