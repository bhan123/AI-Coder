const API_BASE = '/api/v1';

export class StationApiError extends Error {
  constructor(code, message, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new StationApiError(payload.error?.code ?? 'REQUEST_FAILED', payload.error?.message ?? '服务暂时不可用。', response.status);
  }
  return payload;
}

export const stationApi = {
  acceptInvitation(token, displayName) {
    return request('/invitations/accept', { method: 'POST', body: JSON.stringify({ token, displayName }) });
  },
  getStation() {
    return request('/station');
  },
  getEvents() {
    return request('/events');
  },
  initialize(initialScore) {
    return request('/station/initialize', { method: 'POST', body: JSON.stringify({ initialScore }) });
  },
  submitPositive(content, requestedPoints, photoDataUrl) {
    return request('/events/positive', { method: 'POST', body: JSON.stringify({ content, requestedPoints, photoDataUrl }) });
  },
  reviewPositive(eventId, decision, effectivePoints) {
    return request(`/events/${encodeURIComponent(eventId)}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, effectivePoints }),
    });
  },
  recordNegative(content, points) {
    return request('/events/negative', { method: 'POST', body: JSON.stringify({ content, points }) });
  },
  submitRepair(eventId, content) {
    return request(`/events/${encodeURIComponent(eventId)}/repair`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    });
  },
  completeRepair(eventId) {
    return request(`/events/${encodeURIComponent(eventId)}/repair/complete`, { method: 'POST' });
  },
};
