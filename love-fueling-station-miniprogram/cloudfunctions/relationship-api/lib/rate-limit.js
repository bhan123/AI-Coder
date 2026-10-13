function nextRateLimitState(current, currentTime, rule) {
  if (!rule || !Number.isInteger(rule.limit) || !Number.isInteger(rule.windowMs)) throw new Error('频控规则无效。');
  const windowStartedAt = current && Number.isFinite(current.windowStartedAt) ? current.windowStartedAt : currentTime;
  if (!current || currentTime - windowStartedAt >= rule.windowMs) {
    return { allowed: true, state: { count: 1, windowStartedAt: currentTime, expiresAt: new Date(currentTime + rule.windowMs).toISOString() } };
  }
  if (current.count >= rule.limit) return { allowed: false, state: current };
  return { allowed: true, state: { ...current, count: current.count + 1 } };
}

module.exports = { nextRateLimitState };
