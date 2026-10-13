import { validateReviewRange } from './review-center.js'

export const COLLECTION_PAGE_SIZE = 25
export const COLLECTION_STATUSES = { pending: '待采集', running: '运行中', failed: '采集失败', completed: '已完成采集' }
const AVAILABILITY = {
  completed: { label: '已完成采集', tone: 'complete', note: '仅此收盘采集完成，不代表限价、触板等证据齐全。' },
  awaiting_close: { label: '等待补采时段', tone: 'waiting', note: '目标日16:00起允许日线补采；不是立即执行承诺。' },
  cooldown: { label: '失败冷却中', tone: 'warning', note: '等待已记录的重试时间；查看尝试记录了解失败类别。' },
  running: { label: '正在采集', tone: 'waiting', note: '租约仍有效，不重复领取任务。' },
  lease_expired: { label: '租约过期，待接续', tone: 'warning', note: '等待采集工作器接续；查看记录不会自动恢复任务。' },
  ready: { label: '允许处理，待调度', tone: 'waiting', note: '当前队列时间条件允许处理，不保证行情已就绪或立即执行。' },
  unknown: { label: '状态待核查', tone: 'warning', note: '记录状态或时间证据不足，不能推定已就绪。' },
}

export function collectionAvailability(job) {
  const key = job?.availability
  if (['ready', 'lease_expired'].includes(key) && job.ready_to_collect !== true) return AVAILABILITY.unknown
  return Object.hasOwn(AVAILABILITY, key) ? AVAILABILITY[key] : AVAILABILITY.unknown
}

export function collectionQuery(range, { code = '', status = '', offset = 0 } = {}) {
  const error = validateReviewRange(range.date_from, range.date_to)
  if (error) throw new Error(error)
  const normalizedCode = code.trim()
  if (normalizedCode && !/^[0-9]{6}$/.test(normalizedCode)) throw new Error('股票代码须为六位数字。')
  if (status && !Object.hasOwn(COLLECTION_STATUSES, status)) throw new Error('采集状态无效。')
  if (!Number.isInteger(offset) || offset < 0 || offset > 1000000) throw new Error('分页位置无效。')
  return { date_from: range.date_from, date_to: range.date_to, code: normalizedCode, status, offset, limit: COLLECTION_PAGE_SIZE }
}

export function collectionPageError(data, kind = 'jobs') {
  const invalid = '补采诊断接口数据不完整或版本不匹配，请更新后端后重试；不能据此判断没有任务。'
  if (!data || !['available', 'not_initialized'].includes(data.queue_status) || !Array.isArray(data.items)
      || !Number.isInteger(data.total) || data.total < 0 || !Number.isInteger(data.offset) || data.offset < 0
      || !Number.isInteger(data.limit) || data.limit < 1 || data.limit > 200 || data.items.length > data.limit) return invalid
  const end = data.offset + data.items.length
  if (data.items.length && end > data.total || !data.items.length && data.offset < data.total) return invalid
  if (end < data.total ? data.next_offset !== end : data.next_offset !== null) return invalid
  if (data.queue_status === 'not_initialized' && data.total !== 0) return invalid
  if (data.items.some(row => !row || !/^[0-9]{6}$/.test(row.code) || typeof row.trade_date !== 'string'
      || typeof row.provider !== 'string' || !row.provider || typeof row.status !== 'string'
      || (kind === 'attempts' ? !Number.isInteger(row.sequence) : !Number.isInteger(row.attempt_count)))) return invalid
  if (kind === 'jobs') {
    const counts = data.counts_by_status
    if (!counts || typeof counts !== 'object' || Array.isArray(counts)) return invalid
    const values = Object.values(counts)
    if (values.some(value => !Number.isInteger(value) || value < 0) || values.reduce((a, b) => a + b, 0) !== data.total) return invalid
  }
  return ''
}
