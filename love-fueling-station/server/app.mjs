import { createHash, createHmac, randomBytes, randomUUID, timingSafeEqual } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { createServer } from 'node:http';

const MAX_BODY_BYTES = 32 * 1024;
const MAX_ACTION_BODY_BYTES = 1200 * 1024;
const MAX_PHOTO_BYTES = 800 * 1024;
function json(response, status, body) {
  response.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
  });
  response.end(JSON.stringify(body));
}

function base64Url(value) {
  return Buffer.from(value).toString('base64url');
}

function sign(value, secret) {
  return createHmac('sha256', secret).update(value).digest('base64url');
}

function digestToken(token) {
  return createHash('sha256').update(token).digest('hex');
}

function parseJsonBody(request, maxBodyBytes = MAX_BODY_BYTES) {
  return new Promise((resolve, reject) => {
    let size = 0;
    let raw = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      size += Buffer.byteLength(chunk);
      if (size > maxBodyBytes) {
        reject(new ApiError(413, 'BODY_TOO_LARGE', '请求内容过大。'));
        request.destroy();
        return;
      }
      raw += chunk;
    });
    request.on('end', () => {
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new ApiError(400, 'INVALID_JSON', '请求格式不正确。'));
      }
    });
    request.on('error', reject);
  });
}

class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function issueSessionToken(memberId, secret) {
  const issuedAt = Math.floor(Date.now() / 1000);
  const payload = base64Url(JSON.stringify({ sub: memberId, iat: issuedAt }));
  return `${payload}.${sign(payload, secret)}`;
}

function verifySessionToken(token, secret) {
  const [payload, receivedSignature] = token.split('.');
  if (!payload || !receivedSignature) return null;
  const expectedSignature = sign(payload, secret);
  const received = Buffer.from(receivedSignature);
  const expected = Buffer.from(expectedSignature);
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) return null;

  try {
    const session = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    return typeof session.sub === 'string' ? session : null;
  } catch {
    return null;
  }
}

function migrate(database) {
  database.exec(`
    PRAGMA foreign_keys = ON;

    CREATE TABLE IF NOT EXISTS stations (
      id TEXT PRIMARY KEY,
      status TEXT NOT NULL DEFAULT 'awaiting_initialization'
        CHECK (status IN ('awaiting_initialization', 'active', 'paused')),
      score_baseline INTEGER CHECK (score_baseline BETWEEN 0 AND 100),
      baseline_selected_by TEXT,
      baseline_selected_at TEXT,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS members (
      id TEXT PRIMARY KEY,
      station_id TEXT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
      role TEXT NOT NULL CHECK (role IN ('wife', 'husband')),
      display_name TEXT NOT NULL,
      created_at TEXT NOT NULL,
      UNIQUE(station_id, role)
    );

    CREATE TABLE IF NOT EXISTS invitations (
      id TEXT PRIMARY KEY,
      station_id TEXT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
      role TEXT NOT NULL CHECK (role IN ('wife', 'husband')),
      token_digest TEXT NOT NULL UNIQUE,
      expires_at TEXT NOT NULL,
      accepted_at TEXT,
      created_at TEXT NOT NULL,
      UNIQUE(station_id, role)
    );

    CREATE TABLE IF NOT EXISTS audit_entries (
      id TEXT PRIMARY KEY,
      station_id TEXT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
      actor_id TEXT NOT NULL REFERENCES members(id),
      action TEXT NOT NULL,
      entity_id TEXT NOT NULL,
      metadata_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS audit_entries_station_created_idx
      ON audit_entries(station_id, created_at DESC);

    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY,
      station_id TEXT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
      event_type TEXT NOT NULL CHECK (event_type IN ('positive', 'negative')),
      content TEXT NOT NULL,
      requested_points INTEGER,
      effective_points INTEGER,
      status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'deducted')),
      created_by TEXT NOT NULL REFERENCES members(id),
      resolved_by TEXT REFERENCES members(id),
      resolved_at TEXT,
      photo_mime TEXT,
      photo_blob BLOB,
      repair_status TEXT,
      repair_content TEXT,
      repair_created_by TEXT,
      repair_created_at TEXT,
      repair_completed_by TEXT,
      repair_completed_at TEXT,
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS events_station_created_idx
      ON events(station_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS events_station_status_idx
      ON events(station_id, status, created_at DESC);
  `);

  const eventColumns = database.prepare('PRAGMA table_info(events)').all();
  if (!eventColumns.some((column) => column.name === 'photo_mime')) database.exec('ALTER TABLE events ADD COLUMN photo_mime TEXT');
  if (!eventColumns.some((column) => column.name === 'photo_blob')) database.exec('ALTER TABLE events ADD COLUMN photo_blob BLOB');
  if (!eventColumns.some((column) => column.name === 'repair_status')) database.exec('ALTER TABLE events ADD COLUMN repair_status TEXT');
  if (!eventColumns.some((column) => column.name === 'repair_content')) database.exec('ALTER TABLE events ADD COLUMN repair_content TEXT');
  if (!eventColumns.some((column) => column.name === 'repair_created_by')) database.exec('ALTER TABLE events ADD COLUMN repair_created_by TEXT');
  if (!eventColumns.some((column) => column.name === 'repair_created_at')) database.exec('ALTER TABLE events ADD COLUMN repair_created_at TEXT');
  if (!eventColumns.some((column) => column.name === 'repair_completed_by')) database.exec('ALTER TABLE events ADD COLUMN repair_completed_by TEXT');
  if (!eventColumns.some((column) => column.name === 'repair_completed_at')) database.exec('ALTER TABLE events ADD COLUMN repair_completed_at TEXT');
}

function stationView(station, currentScore) {
  return {
    id: station.id,
    status: station.status,
    initialScore: station.score_baseline,
    initializedAt: station.baseline_selected_at,
    currentScore,
  };
}

function eventView(event) {
  return {
    id: event.id,
    type: event.event_type,
    content: event.content,
    requestedPoints: event.requested_points,
    points: event.effective_points ?? event.requested_points ?? 0,
    status: event.status,
    createdAt: event.created_at,
    resolvedAt: event.resolved_at,
    hasPhoto: Boolean(event.has_photo ?? event.photo_blob),
    repairStatus: event.event_type === 'negative' ? event.repair_status ?? 'needs_response' : null,
    repairContent: event.repair_content ?? null,
    repairCreatedAt: event.repair_created_at ?? null,
    repairCompletedAt: event.repair_completed_at ?? null,
  };
}

function parsePhotoDataUrl(photoDataUrl) {
  if (photoDataUrl === undefined || photoDataUrl === null || photoDataUrl === '') return { photoMime: null, photoBlob: null };
  if (typeof photoDataUrl !== 'string') throw new ApiError(400, 'INVALID_PHOTO', '照片格式不正确。');
  const match = photoDataUrl.match(/^data:(image\/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)$/);
  if (!match) throw new ApiError(400, 'INVALID_PHOTO', '照片仅支持 JPG、PNG 或 WebP。');
  const photoBlob = Buffer.from(match[2], 'base64');
  if (photoBlob.length === 0 || photoBlob.length > MAX_PHOTO_BYTES) {
    throw new ApiError(413, 'PHOTO_TOO_LARGE', '照片处理后不能超过800KB。');
  }
  return { photoMime: match[1], photoBlob };
}

function assertText(value, { field, min, max }) {
  if (typeof value !== 'string' || value.trim().length < min || value.trim().length > max) {
    throw new ApiError(400, `INVALID_${field.toUpperCase()}`, `${field}需为${min}到${max}个字符。`);
  }
  return value.trim();
}

function assertPoints(value, allowed, code) {
  if (!Number.isInteger(value) || !allowed.includes(value)) {
    throw new ApiError(400, code, '分值不在可选范围内。');
  }
  return value;
}

export function createStore({ databasePath = ':memory:' } = {}) {
  const database = new DatabaseSync(databasePath);
  migrate(database);

  return {
    createPair({ stationId = randomUUID(), wifeName = '她', husbandName = '他' } = {}) {
      const now = new Date().toISOString();
      const wifeId = randomUUID();
      const husbandId = randomUUID();
      database.exec('BEGIN IMMEDIATE');
      try {
        database.prepare('INSERT INTO stations (id, created_at) VALUES (?, ?)').run(stationId, now);
        database.prepare('INSERT INTO members (id, station_id, role, display_name, created_at) VALUES (?, ?, ?, ?, ?)').run(wifeId, stationId, 'wife', wifeName, now);
        database.prepare('INSERT INTO members (id, station_id, role, display_name, created_at) VALUES (?, ?, ?, ?, ?)').run(husbandId, stationId, 'husband', husbandName, now);
        database.exec('COMMIT');
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
      return { stationId, wifeId, husbandId };
    },

    createInvitationPair({ stationId = randomUUID(), expiresInDays = 7 } = {}) {
      const now = new Date();
      const expiresAt = new Date(now.getTime() + expiresInDays * 24 * 60 * 60 * 1000).toISOString();
      const wifeToken = randomBytes(32).toString('base64url');
      const husbandToken = randomBytes(32).toString('base64url');
      database.exec('BEGIN IMMEDIATE');
      try {
        database.prepare('INSERT INTO stations (id, created_at) VALUES (?, ?)').run(stationId, now.toISOString());
        const insertInvitation = database.prepare(`
          INSERT INTO invitations (id, station_id, role, token_digest, expires_at, created_at)
          VALUES (?, ?, ?, ?, ?, ?)
        `);
        insertInvitation.run(randomUUID(), stationId, 'wife', digestToken(wifeToken), expiresAt, now.toISOString());
        insertInvitation.run(randomUUID(), stationId, 'husband', digestToken(husbandToken), expiresAt, now.toISOString());
        database.exec('COMMIT');
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
      return { stationId, wifeToken, husbandToken, expiresAt };
    },

    acceptInvitation({ token, displayName }) {
      if (typeof token !== 'string' || token.length < 32) throw new ApiError(400, 'INVALID_INVITATION', '邀请链接无效。');
      if (typeof displayName !== 'string' || displayName.trim().length < 1 || displayName.trim().length > 24) {
        throw new ApiError(400, 'INVALID_DISPLAY_NAME', '请填写1到24个字符的称呼。');
      }

      database.exec('BEGIN IMMEDIATE');
      try {
        const invitation = database.prepare(`
          SELECT * FROM invitations WHERE token_digest = ?
        `).get(digestToken(token));
        if (!invitation || invitation.accepted_at !== null) throw new ApiError(410, 'INVITATION_UNAVAILABLE', '邀请链接已失效或已被使用。');
        if (new Date(invitation.expires_at).getTime() <= Date.now()) throw new ApiError(410, 'INVITATION_EXPIRED', '邀请链接已过期。');

        const memberId = randomUUID();
        const now = new Date().toISOString();
        database.prepare(`
          INSERT INTO members (id, station_id, role, display_name, created_at)
          VALUES (?, ?, ?, ?, ?)
        `).run(memberId, invitation.station_id, invitation.role, displayName.trim(), now);
        database.prepare('UPDATE invitations SET accepted_at = ? WHERE id = ? AND accepted_at IS NULL').run(now, invitation.id);
        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), invitation.station_id, memberId, 'invitation_accepted', invitation.id, JSON.stringify({ role: invitation.role }), now);
        database.exec('COMMIT');
        return this.getMember(memberId);
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    getMember(memberId) {
      return database.prepare(`
        SELECT members.id, members.station_id, members.role, members.display_name,
          stations.status, stations.score_baseline, stations.baseline_selected_at
        FROM members JOIN stations ON stations.id = members.station_id
        WHERE members.id = ?
      `).get(memberId);
    },

    getStation(stationId) {
      return database.prepare('SELECT * FROM stations WHERE id = ?').get(stationId);
    },

    getCurrentScore(stationId, now = new Date()) {
      const station = this.getStation(stationId);
      if (!station || station.score_baseline === null) return null;
      const cutoff = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString();
      const change = database.prepare(`
        SELECT COALESCE(SUM(effective_points), 0) AS points
        FROM events
        WHERE station_id = ?
          AND status IN ('approved', 'deducted')
          AND created_at >= ?
      `).get(stationId, cutoff);
      return Math.max(0, Math.min(100, station.score_baseline + change.points));
    },

    getStationView(stationId) {
      const station = this.getStation(stationId);
      if (!station) return null;
      return stationView(station, this.getCurrentScore(stationId));
    },

    listEvents(stationId) {
      return database.prepare(`
        SELECT id, station_id, event_type, content, requested_points, effective_points, status,
          created_by, resolved_by, resolved_at, created_at, photo_mime,
          repair_status, repair_content, repair_created_by, repair_created_at, repair_completed_by, repair_completed_at,
          (photo_blob IS NOT NULL) AS has_photo
        FROM events WHERE station_id = ? ORDER BY created_at DESC, id DESC
      `).all(stationId).map(eventView);
    },

    getEventPhoto(stationId, eventId) {
      return database.prepare(`
        SELECT photo_mime, photo_blob FROM events WHERE id = ? AND station_id = ?
      `).get(eventId, stationId);
    },

    requireActiveMember(actorId) {
      const member = this.getMember(actorId);
      if (!member) throw new ApiError(401, 'INVALID_SESSION', '登录状态无效。');
      if (member.status !== 'active') throw new ApiError(409, 'STATION_NOT_INITIALIZED', '请先由女方设定初始温度。');
      return member;
    },

    submitPositiveEvent({ actorId, content, requestedPoints, photoDataUrl }) {
      const normalizedContent = assertText(content, { field: '行动内容', min: 2, max: 300 });
      assertPoints(requestedPoints, [1, 3, 5], 'INVALID_REQUESTED_POINTS');
      const { photoMime, photoBlob } = parsePhotoDataUrl(photoDataUrl);
      database.exec('BEGIN IMMEDIATE');
      try {
        const member = this.requireActiveMember(actorId);
        if (member.role !== 'husband') throw new ApiError(403, 'HUSBAND_ONLY', '爱的行动只能由男方账号提交。');
        const now = new Date().toISOString();
        const event = {
          id: randomUUID(), stationId: member.station_id, eventType: 'positive', content: normalizedContent,
          requestedPoints, status: 'pending', actorId, now,
        };
        database.prepare(`
          INSERT INTO events (id, station_id, event_type, content, requested_points, status, created_by, photo_mime, photo_blob, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).run(event.id, event.stationId, event.eventType, event.content, event.requestedPoints, event.status, event.actorId, photoMime, photoBlob, event.now);
        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), event.stationId, actorId, 'positive_event_submitted', event.id, JSON.stringify({ requestedPoints }), now);
        database.exec('COMMIT');
        return eventView(database.prepare('SELECT * FROM events WHERE id = ?').get(event.id));
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    reviewPositiveEvent({ actorId, eventId, decision, effectivePoints }) {
      if (!['approved', 'rejected'].includes(decision)) throw new ApiError(400, 'INVALID_DECISION', '请给出通过或驳回的决定。');
      if (decision === 'approved') assertPoints(effectivePoints, [1, 3, 5], 'INVALID_EFFECTIVE_POINTS');
      database.exec('BEGIN IMMEDIATE');
      try {
        const member = this.requireActiveMember(actorId);
        if (member.role !== 'wife') throw new ApiError(403, 'WIFE_ONLY', '只有女方账号可以审批行动。');
        const event = database.prepare('SELECT * FROM events WHERE id = ? AND station_id = ?').get(eventId, member.station_id);
        if (!event || event.event_type !== 'positive') throw new ApiError(404, 'EVENT_NOT_FOUND', '未找到这条行动记录。');
        if (event.status !== 'pending') throw new ApiError(409, 'EVENT_ALREADY_RESOLVED', '这条行动已经处理过了。');
        const now = new Date().toISOString();
        database.prepare(`
          UPDATE events SET status = ?, effective_points = ?, resolved_by = ?, resolved_at = ?
          WHERE id = ? AND status = 'pending'
        `).run(decision, decision === 'approved' ? effectivePoints : null, actorId, now, eventId);
        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), member.station_id, actorId, `positive_event_${decision}`, eventId, JSON.stringify({ effectivePoints: decision === 'approved' ? effectivePoints : null }), now);
        database.exec('COMMIT');
        return eventView(database.prepare('SELECT * FROM events WHERE id = ?').get(eventId));
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    createNegativeEvent({ actorId, content, points }) {
      const normalizedContent = assertText(content, { field: '感受内容', min: 2, max: 180 });
      assertPoints(points, [-1, -3, -5], 'INVALID_DEDUCTION_POINTS');
      database.exec('BEGIN IMMEDIATE');
      try {
        const member = this.requireActiveMember(actorId);
        if (member.role !== 'wife') throw new ApiError(403, 'WIFE_ONLY', '只有女方账号可以直接记录不舒服。');
        const now = new Date().toISOString();
        const eventId = randomUUID();
        database.prepare(`
          INSERT INTO events (id, station_id, event_type, content, effective_points, status, created_by, resolved_by, resolved_at, created_at)
          VALUES (?, ?, 'negative', ?, ?, 'deducted', ?, ?, ?, ?)
        `).run(eventId, member.station_id, normalizedContent, points, actorId, actorId, now, now);
        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), member.station_id, actorId, 'negative_event_recorded', eventId, JSON.stringify({ points }), now);
        database.exec('COMMIT');
        return eventView(database.prepare('SELECT * FROM events WHERE id = ?').get(eventId));
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    submitRepair({ actorId, eventId, content }) {
      const normalizedContent = assertText(content, { field: '修复行动', min: 2, max: 300 });
      database.exec('BEGIN IMMEDIATE');
      try {
        const member = this.requireActiveMember(actorId);
        if (member.role !== 'husband') throw new ApiError(403, 'HUSBAND_ONLY', '只有男方账号可以提交修复行动。');
        const event = database.prepare('SELECT * FROM events WHERE id = ? AND station_id = ?').get(eventId, member.station_id);
        if (!event || event.event_type !== 'negative') throw new ApiError(404, 'EVENT_NOT_FOUND', '未找到这条需要修复的记录。');
        if (event.repair_status === 'repaired') throw new ApiError(409, 'REPAIR_ALREADY_COMPLETED', '这件事已经完成修复。');
        if (event.repair_status === 'repairing') throw new ApiError(409, 'REPAIR_ALREADY_SUBMITTED', '修复行动已经提交，正在等待她确认。');
        const now = new Date().toISOString();
        database.prepare(`
          UPDATE events
          SET repair_status = 'repairing', repair_content = ?, repair_created_by = ?, repair_created_at = ?
          WHERE id = ? AND station_id = ?
        `).run(normalizedContent, actorId, now, eventId, member.station_id);
        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), member.station_id, actorId, 'negative_event_repair_submitted', eventId, JSON.stringify({}), now);
        database.exec('COMMIT');
        return eventView(database.prepare('SELECT * FROM events WHERE id = ?').get(eventId));
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    completeRepair({ actorId, eventId }) {
      database.exec('BEGIN IMMEDIATE');
      try {
        const member = this.requireActiveMember(actorId);
        if (member.role !== 'wife') throw new ApiError(403, 'WIFE_ONLY', '只有女方账号可以确认修复完成。');
        const event = database.prepare('SELECT * FROM events WHERE id = ? AND station_id = ?').get(eventId, member.station_id);
        if (!event || event.event_type !== 'negative') throw new ApiError(404, 'EVENT_NOT_FOUND', '未找到这条需要修复的记录。');
        if (event.repair_status === 'repaired') throw new ApiError(409, 'REPAIR_ALREADY_COMPLETED', '这件事已经完成修复。');
        if (event.repair_status !== 'repairing') throw new ApiError(409, 'REPAIR_NOT_SUBMITTED', '请先等待他提交修复行动。');
        const now = new Date().toISOString();
        database.prepare(`
          UPDATE events
          SET repair_status = 'repaired', repair_completed_by = ?, repair_completed_at = ?
          WHERE id = ? AND station_id = ? AND repair_status = 'repairing'
        `).run(actorId, now, eventId, member.station_id);
        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), member.station_id, actorId, 'negative_event_repair_completed', eventId, JSON.stringify({}), now);
        database.exec('COMMIT');
        return eventView(database.prepare('SELECT * FROM events WHERE id = ?').get(eventId));
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    initializeStation({ actorId, initialScore }) {
      if (!Number.isInteger(initialScore) || initialScore < 0 || initialScore > 100) {
        throw new ApiError(400, 'INVALID_INITIAL_SCORE', '初始温度必须是0到100之间的整数。');
      }

      database.exec('BEGIN IMMEDIATE');
      try {
        const member = this.getMember(actorId);
        if (!member) throw new ApiError(401, 'INVALID_SESSION', '登录状态无效。');
        if (member.role !== 'wife') throw new ApiError(403, 'WIFE_ONLY', '初始温度只能由女方账号设定。');
        if (member.score_baseline !== null) throw new ApiError(409, 'ALREADY_INITIALIZED', '初始温度已经设定，不能直接修改。');

        const now = new Date().toISOString();
        const change = database.prepare(`
          UPDATE stations
          SET score_baseline = ?, baseline_selected_by = ?, baseline_selected_at = ?, status = 'active'
          WHERE id = ? AND score_baseline IS NULL
        `).run(initialScore, actorId, now, member.station_id);
        if (change.changes !== 1) throw new ApiError(409, 'ALREADY_INITIALIZED', '初始温度已经设定，不能直接修改。');

        database.prepare(`
          INSERT INTO audit_entries (id, station_id, actor_id, action, entity_id, metadata_json, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
        `).run(randomUUID(), member.station_id, actorId, 'station_initialized', member.station_id, JSON.stringify({ initialScore }), now);
        database.exec('COMMIT');
        return this.getStationView(member.station_id);
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },

    listAudits(stationId) {
      return database.prepare('SELECT * FROM audit_entries WHERE station_id = ? ORDER BY created_at').all(stationId);
    },

    close() {
      database.close();
    },
  };
}

function readSessionToken(request) {
  const authorization = request.headers.authorization;
  if (authorization?.startsWith('Bearer ')) return authorization.slice('Bearer '.length);
  const cookie = request.headers.cookie?.split(';').map((part) => part.trim()).find((part) => part.startsWith('lfs_session='));
  return cookie ? decodeURIComponent(cookie.slice('lfs_session='.length)) : null;
}

function requireMember(request, store, secret) {
  const token = readSessionToken(request);
  if (!token) throw new ApiError(401, 'AUTH_REQUIRED', '请先完成身份验证。');
  const session = verifySessionToken(token, secret);
  if (!session) throw new ApiError(401, 'INVALID_SESSION', '登录状态无效。');
  const member = store.getMember(session.sub);
  if (!member) throw new ApiError(401, 'INVALID_SESSION', '登录状态无效。');
  return member;
}

export function createApiServer({ store = createStore(), sessionSecret = 'development-only-secret', secureCookies = false } = {}) {
  return createServer(async (request, response) => {
    try {
      const url = new URL(request.url, `http://${request.headers.host ?? 'localhost'}`);
      if (request.method === 'GET' && url.pathname === '/api/v1/health') {
        return json(response, 200, { status: 'ok' });
      }

      if (request.method === 'GET' && url.pathname === '/api/v1/station') {
        const member = requireMember(request, store, sessionSecret);
        return json(response, 200, {
          station: store.getStationView(member.station_id),
          member: { id: member.id, role: member.role, displayName: member.display_name },
        });
      }

      if (request.method === 'GET' && url.pathname === '/api/v1/events') {
        const member = requireMember(request, store, sessionSecret);
        return json(response, 200, { events: store.listEvents(member.station_id) });
      }

      if (request.method === 'POST' && url.pathname === '/api/v1/invitations/accept') {
        const body = await parseJsonBody(request);
        const member = store.acceptInvitation({ token: body.token, displayName: body.displayName });
        const sessionToken = issueSessionToken(member.id, sessionSecret);
        response.setHeader('Set-Cookie', [
          `lfs_session=${encodeURIComponent(sessionToken)}`,
          'HttpOnly',
          'Path=/',
          'SameSite=Lax',
          'Max-Age=2592000',
          secureCookies ? 'Secure' : '',
        ].filter(Boolean).join('; '));
        return json(response, 201, {
          station: store.getStationView(member.station_id),
          member: { id: member.id, role: member.role, displayName: member.display_name },
        });
      }

      if (request.method === 'POST' && url.pathname === '/api/v1/station/initialize') {
        const member = requireMember(request, store, sessionSecret);
        const body = await parseJsonBody(request);
        const station = store.initializeStation({ actorId: member.id, initialScore: body.initialScore });
        return json(response, 201, { station });
      }

      if (request.method === 'POST' && url.pathname === '/api/v1/events/positive') {
        const member = requireMember(request, store, sessionSecret);
        const body = await parseJsonBody(request, MAX_ACTION_BODY_BYTES);
        const event = store.submitPositiveEvent({ actorId: member.id, content: body.content, requestedPoints: body.requestedPoints, photoDataUrl: body.photoDataUrl });
        return json(response, 201, { event });
      }

      const photoMatch = url.pathname.match(/^\/api\/v1\/events\/([^/]+)\/photo$/);
      if (request.method === 'GET' && photoMatch) {
        const member = requireMember(request, store, sessionSecret);
        const photo = store.getEventPhoto(member.station_id, photoMatch[1]);
        if (!photo?.photo_blob) throw new ApiError(404, 'PHOTO_NOT_FOUND', '未找到这张照片。');
        response.writeHead(200, {
          'Content-Type': photo.photo_mime,
          'Content-Length': photo.photo_blob.length,
          'Cache-Control': 'private, max-age=3600',
          'X-Content-Type-Options': 'nosniff',
          'Content-Security-Policy': "default-src 'none'; sandbox",
        });
        response.end(Buffer.from(photo.photo_blob));
        return undefined;
      }

      const reviewMatch = url.pathname.match(/^\/api\/v1\/events\/([^/]+)\/review$/);
      if (request.method === 'POST' && reviewMatch) {
        const member = requireMember(request, store, sessionSecret);
        const body = await parseJsonBody(request);
        const event = store.reviewPositiveEvent({ actorId: member.id, eventId: reviewMatch[1], decision: body.decision, effectivePoints: body.effectivePoints });
        return json(response, 200, { event, station: store.getStationView(member.station_id) });
      }

      if (request.method === 'POST' && url.pathname === '/api/v1/events/negative') {
        const member = requireMember(request, store, sessionSecret);
        const body = await parseJsonBody(request);
        const event = store.createNegativeEvent({ actorId: member.id, content: body.content, points: body.points });
        return json(response, 201, { event, station: store.getStationView(member.station_id) });
      }

      const repairCompleteMatch = url.pathname.match(/^\/api\/v1\/events\/([^/]+)\/repair\/complete$/);
      if (request.method === 'POST' && repairCompleteMatch) {
        const member = requireMember(request, store, sessionSecret);
        const event = store.completeRepair({ actorId: member.id, eventId: repairCompleteMatch[1] });
        return json(response, 200, { event, station: store.getStationView(member.station_id) });
      }

      const repairMatch = url.pathname.match(/^\/api\/v1\/events\/([^/]+)\/repair$/);
      if (request.method === 'POST' && repairMatch) {
        const member = requireMember(request, store, sessionSecret);
        const body = await parseJsonBody(request);
        const event = store.submitRepair({ actorId: member.id, eventId: repairMatch[1], content: body.content });
        return json(response, 200, { event, station: store.getStationView(member.station_id) });
      }

      return json(response, 404, { error: { code: 'NOT_FOUND', message: '接口不存在。' } });
    } catch (error) {
      if (error instanceof ApiError) return json(response, error.status, { error: { code: error.code, message: error.message } });
      console.error(error);
      return json(response, 500, { error: { code: 'INTERNAL_ERROR', message: '服务暂时不可用。' } });
    }
  });
}
