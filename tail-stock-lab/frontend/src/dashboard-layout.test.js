import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

test('dashboard presents V1 signals before the T+1 review and history archive', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  const signals = source.indexOf('<section id="recommendations"')
  const review = source.indexOf('<T1ReviewPanel review={t1Review} error={t1ReviewError} />')
  const history = source.indexOf('<HistoryPanel')

  assert.ok(signals >= 0)
  assert.ok(review > signals)
  assert.ok(history > review)
})

test('T+1 review does not promote paper net return as a table metric', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /<th>净收益<\/th>/)
  assert.doesNotMatch(source, /review-return/)
})

test('opening a historical snapshot returns the reader to the recommendation list', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /const signalAreaRef = useRef\(null\)/)
  assert.match(source, /signalAreaRef\.current\?\.scrollIntoView\(\{ behavior: 'auto', block: 'start' \}\)/)
  assert.match(source, /<section id="recommendations" ref=\{signalAreaRef\} className="content-grid">/)
})

test('signal details expand beneath the selected stock instead of occupying a side panel', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /function SignalDetails\(/)
  assert.match(source, /selected\?\.code === signal\.code && <tr className="signal-details-row">/)
  assert.doesNotMatch(source, /<aside className="inspector">/)
})

test('V1 candidates do not expose unverified P1-P4 suitability placeholders', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.doesNotMatch(source, /function PriorityTags\(/)
  assert.doesNotMatch(source, /优先级策略适配/)
  assert.doesNotMatch(source, /const STATUS_FILTERS/)
  assert.doesNotMatch(source, /优先级标签/)
})

test('the intraday alert feed is separate from V1 history and T+1 review', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /function IntradayAlertPanel\(/)
  assert.match(source, /<IntradayAlertPanel alertRun=\{alertRun\} \/>/)
  assert.doesNotMatch(source, /<HistoryPanel[^>]*limit-up-ambush/)
})

test('latest intraday alerts explain normalized limit progress and momentum confirmation', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /涨停进度/)
  assert.match(source, /连续增强确认/)
})

test('intraday alert history is summary-first, deduplicated and expandable', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /function AlertHistoryPanel\(/)
  assert.match(source, /扫描次数/)
  assert.match(source, /预警股票/)
  assert.match(source, /持续预警/)
  assert.match(source, /触及涨停/)
  assert.match(source, /首次 \/ 末次/)
  assert.match(source, /预警后最高/)
  assert.match(source, /function AlertTimeline\(/)
  assert.match(source, /expandedCode === event\.code/)
})

test('intraday alert history exposes score and hit-count sorting controls', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /aria-label="预警历史排序"/)
  assert.match(source, /value="hit_count_desc"/)
  assert.match(source, /value="max_score_desc"/)
  assert.match(source, /sortAlertEvents\(events, sortBy\)/)
})

test('new alert history calls momentum-qualified repeats strengthening counts', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /history\?\.count_semantics === 'strengthening'/)
  assert.match(source, /history\?\.count_semantics === 'mixed'/)
  assert.match(source, /连续增强次数/)
  assert.match(source, /命中\/增强次数/)
  assert.match(source, /持续增强/)
})

test('sortable alert-history headers expose paired direction triangles', async () => {
  const source = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')

  assert.match(source, /function SortableAlertHeader\(/)
  assert.match(source, /aria-sort=/)
  assert.match(source, /className="sort-triangle up"/)
  assert.match(source, /className="sort-triangle down"/)
  assert.match(source, /<SortableAlertHeader label="最高评分" field="max_score"/)
  assert.match(source, /<SortableAlertHeader label="首次涨幅" field="first_alert_pct"/)
})

test('the product brand is Signal Forge in the page shell and browser title', async () => {
  const appSource = await readFile(new URL('./App.jsx', import.meta.url), 'utf8')
  const htmlSource = await readFile(new URL('../index.html', import.meta.url), 'utf8')

  assert.match(appSource, /className="brand">Signal Forge</)
  assert.match(htmlSource, /<title>Signal Forge<\/title>/)
  assert.doesNotMatch(`${appSource}\n${htmlSource}`, /尾盘策略实验室/)
})
