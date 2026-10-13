const WIDTH = 620
const HEIGHT = 176
const LEFT = 12
const RIGHT = 12
const TOP = 12
const BOTTOM = 28

const round = (value) => Math.round(value * 100) / 100

export function buildT1Chart(review, referencePrices = []) {
  if (!review?.points?.length) return null

  const prices = review.points.map((point) => point.price)
  const references = referencePrices.filter((marker) => Number.isFinite(marker.price))
  const observedLow = Math.min(review.low_price ?? Infinity, ...prices)
  const observedHigh = Math.max(review.high_price ?? -Infinity, ...prices)
  const rawLow = Math.min(observedLow, ...references.map((marker) => marker.price))
  const rawHigh = Math.max(observedHigh, ...references.map((marker) => marker.price))
  const rawSpan = rawHigh - rawLow || Math.max(Math.abs(rawHigh) * 0.01, 0.01)
  const low = rawLow - rawSpan * 0.06
  const high = rawHigh + rawSpan * 0.06
  const span = high - low
  const usableWidth = WIDTH - LEFT - RIGHT
  const usableHeight = HEIGHT - TOP - BOTTOM
  const pointCount = review.points.length
  const coordinateFor = (point, index) => {
    const x = pointCount === 1 ? WIDTH / 2 : LEFT + (usableWidth * index) / (pointCount - 1)
    const y = TOP + ((high - point.price) / span) * usableHeight
    return { ...point, x: round(x), y: round(y) }
  }
  const points = review.points.map(coordinateFor)
  const valueToY = (price) => round(TOP + ((high - price) / span) * usableHeight)

  return {
    width: WIDTH,
    height: HEIGHT,
    points,
    polyline: points.map((point) => `${point.x},${point.y}`).join(' '),
    openPrice: review.open_price,
    highPrice: observedHigh,
    lowPrice: observedLow,
    lastPrice: review.last_price,
    minLabel: observedLow,
    maxLabel: observedHigh,
    firstTime: points[0].time,
    lastTime: points.at(-1).time,
    markers: references.map((marker) => ({ ...marker, y: valueToY(marker.price) })),
  }
}
