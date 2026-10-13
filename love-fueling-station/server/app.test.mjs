import assert from 'node:assert/strict';
import test from 'node:test';
import { createApiServer, createStore, issueSessionToken } from './app.mjs';

const sessionSecret = 'test-secret-that-is-long-enough-to-sign-sessions';

async function withApi(run) {
  const store = createStore();
  const pair = store.createPair({ wifeName: '小雨', husbandName: '阿泽' });
  const server = createApiServer({ store, sessionSecret });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  const baseUrl = `http://127.0.0.1:${port}`;
  const tokenFor = (memberId) => issueSessionToken(memberId, sessionSecret);

  try {
    await run({ baseUrl, pair, store, tokenFor });
  } finally {
    await new Promise((resolve) => server.close(resolve));
    store.close();
  }
}

function request(baseUrl, token, method, path, body) {
  return fetch(`${baseUrl}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

test('wife can initialize exactly once and the action is audited', async () => {
  await withApi(async ({ baseUrl, pair, store, tokenFor }) => {
    const response = await request(baseUrl, tokenFor(pair.wifeId), 'POST', '/api/v1/station/initialize', { initialScore: 42 });
    assert.equal(response.status, 201);
    const initialized = await response.json();
    assert.equal(initialized.station.id, pair.stationId);
    assert.equal(initialized.station.status, 'active');
    assert.equal(initialized.station.initialScore, 42);
    assert.match(initialized.station.initializedAt, /^\d{4}-\d{2}-\d{2}T/);

    const audits = store.listAudits(pair.stationId);
    assert.equal(audits.length, 1);
    assert.equal(audits[0].action, 'station_initialized');
    assert.deepEqual(JSON.parse(audits[0].metadata_json), { initialScore: 42 });

    const secondResponse = await request(baseUrl, tokenFor(pair.wifeId), 'POST', '/api/v1/station/initialize', { initialScore: 80 });
    assert.equal(secondResponse.status, 409);
    assert.equal((await secondResponse.json()).error.code, 'ALREADY_INITIALIZED');
  });
});

test('husband cannot initialize the station', async () => {
  await withApi(async ({ baseUrl, pair, tokenFor }) => {
    const response = await request(baseUrl, tokenFor(pair.husbandId), 'POST', '/api/v1/station/initialize', { initialScore: 55 });
    assert.equal(response.status, 403);
    assert.equal((await response.json()).error.code, 'WIFE_ONLY');
  });
});

test('initial score must be an integer from zero to one hundred', async () => {
  await withApi(async ({ baseUrl, pair, tokenFor }) => {
    const response = await request(baseUrl, tokenFor(pair.wifeId), 'POST', '/api/v1/station/initialize', { initialScore: 100.5 });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, 'INVALID_INITIAL_SCORE');
  });
});

test('station data requires a valid session', async () => {
  await withApi(async ({ baseUrl }) => {
    const response = await fetch(`${baseUrl}/api/v1/station`);
    assert.equal(response.status, 401);
    assert.equal((await response.json()).error.code, 'AUTH_REQUIRED');
  });
});

test('a wife invitation grants a cookie session and can initialize the station', async () => {
  const store = createStore();
  const invitationPair = store.createInvitationPair();
  const server = createApiServer({ store, sessionSecret });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  const baseUrl = `http://127.0.0.1:${port}`;

  try {
    const accepted = await fetch(`${baseUrl}/api/v1/invitations/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: invitationPair.wifeToken, displayName: '小雨' }),
    });
    assert.equal(accepted.status, 201);
    const sessionCookie = accepted.headers.get('set-cookie');
    assert.match(sessionCookie, /HttpOnly/);
    assert.equal((await accepted.json()).member.role, 'wife');

    const initialized = await fetch(`${baseUrl}/api/v1/station/initialize`, {
      method: 'POST',
      headers: { Cookie: sessionCookie, 'Content-Type': 'application/json' },
      body: JSON.stringify({ initialScore: 62 }),
    });
    assert.equal(initialized.status, 201);
    assert.equal((await initialized.json()).station.initialScore, 62);

    const reused = await fetch(`${baseUrl}/api/v1/invitations/accept`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token: invitationPair.wifeToken, displayName: '小雨' }),
    });
    assert.equal(reused.status, 410);
    assert.equal((await reused.json()).error.code, 'INVITATION_UNAVAILABLE');
  } finally {
    await new Promise((resolve) => server.close(resolve));
    store.close();
  }
});

test('a husband submits an action and wife approval updates the server score', async () => {
  await withApi(async ({ baseUrl, pair, store, tokenFor }) => {
    const wifeToken = tokenFor(pair.wifeId);
    const husbandToken = tokenFor(pair.husbandId);
    await request(baseUrl, wifeToken, 'POST', '/api/v1/station/initialize', { initialScore: 70 });

    const submitted = await request(baseUrl, husbandToken, 'POST', '/api/v1/events/positive', {
      content: '下班后认真准备了你喜欢的晚饭',
      requestedPoints: 5,
    });
    assert.equal(submitted.status, 201);
    const pendingEvent = (await submitted.json()).event;
    assert.equal(pendingEvent.status, 'pending');
    assert.equal(pendingEvent.points, 5);

    const pendingList = await request(baseUrl, wifeToken, 'GET', '/api/v1/events');
    assert.equal((await pendingList.json()).events.length, 1);

    const approved = await request(baseUrl, wifeToken, 'POST', `/api/v1/events/${pendingEvent.id}/review`, {
      decision: 'approved',
      effectivePoints: 3,
    });
    assert.equal(approved.status, 200);
    assert.equal((await approved.json()).station.currentScore, 73);

    const station = await request(baseUrl, husbandToken, 'GET', '/api/v1/station');
    assert.equal((await station.json()).station.currentScore, 73);
    assert.equal(store.listAudits(pair.stationId).filter((entry) => entry.action === 'positive_event_approved').length, 1);
  });
});

test('wife can record a direct deduction while husband cannot approve or deduct', async () => {
  await withApi(async ({ baseUrl, pair, tokenFor }) => {
    const wifeToken = tokenFor(pair.wifeId);
    const husbandToken = tokenFor(pair.husbandId);
    await request(baseUrl, wifeToken, 'POST', '/api/v1/station/initialize', { initialScore: 40 });

    const husbandDeduction = await request(baseUrl, husbandToken, 'POST', '/api/v1/events/negative', {
      content: '不该绕开你的感受', points: -3,
    });
    assert.equal(husbandDeduction.status, 403);
    assert.equal((await husbandDeduction.json()).error.code, 'WIFE_ONLY');

    const deduction = await request(baseUrl, wifeToken, 'POST', '/api/v1/events/negative', {
      content: '说话时没有认真听完我的感受', points: -5,
    });
    assert.equal(deduction.status, 201);
    assert.equal((await deduction.json()).station.currentScore, 35);

    const husbandPositive = await request(baseUrl, husbandToken, 'POST', '/api/v1/events/positive', {
      content: '主动把家里收拾得干干净净', requestedPoints: 3,
    });
    const event = (await husbandPositive.json()).event;
    const husbandReview = await request(baseUrl, husbandToken, 'POST', `/api/v1/events/${event.id}/review`, {
      decision: 'approved', effectivePoints: 3,
    });
    assert.equal(husbandReview.status, 403);
    assert.equal((await husbandReview.json()).error.code, 'WIFE_ONLY');
  });
});

test('a deduction stays visible until husband repairs it and wife confirms completion', async () => {
  await withApi(async ({ baseUrl, pair, store, tokenFor }) => {
    const wifeToken = tokenFor(pair.wifeId);
    const husbandToken = tokenFor(pair.husbandId);
    await request(baseUrl, wifeToken, 'POST', '/api/v1/station/initialize', { initialScore: 70 });

    const deducted = await request(baseUrl, wifeToken, 'POST', '/api/v1/events/negative', {
      content: '忽略了我的感受', points: -5,
    });
    assert.equal(deducted.status, 201);
    const deduction = (await deducted.json()).event;
    assert.equal(deduction.repairStatus, 'needs_response');

    const submittedRepair = await request(baseUrl, husbandToken, 'POST', `/api/v1/events/${deduction.id}/repair`, {
      content: '先认真听你说完，以后做决定前先问你的感受',
    });
    assert.equal(submittedRepair.status, 200);
    const repairing = await submittedRepair.json();
    assert.equal(repairing.event.repairStatus, 'repairing');
    assert.equal(repairing.event.repairContent, '先认真听你说完，以后做决定前先问你的感受');

    const husbandCannotComplete = await request(baseUrl, husbandToken, 'POST', `/api/v1/events/${deduction.id}/repair/complete`);
    assert.equal(husbandCannotComplete.status, 403);
    assert.equal((await husbandCannotComplete.json()).error.code, 'WIFE_ONLY');

    const completed = await request(baseUrl, wifeToken, 'POST', `/api/v1/events/${deduction.id}/repair/complete`);
    assert.equal(completed.status, 200);
    const completedPayload = await completed.json();
    assert.equal(completedPayload.event.repairStatus, 'repaired');
    assert.equal(completedPayload.station.currentScore, 65);

    const events = (await (await request(baseUrl, wifeToken, 'GET', '/api/v1/events')).json()).events;
    assert.equal(events.length, 1);
    assert.equal(events[0].status, 'deducted');
    assert.equal(events[0].repairStatus, 'repaired');
    assert.equal(store.listAudits(pair.stationId).filter((entry) => entry.action === 'negative_event_repair_completed').length, 1);
  });
});

test('events require an initialized station and valid point selections', async () => {
  await withApi(async ({ baseUrl, pair, tokenFor }) => {
    const husbandToken = tokenFor(pair.husbandId);
    const beforeSetup = await request(baseUrl, husbandToken, 'POST', '/api/v1/events/positive', {
      content: '主动承担了今天的家务安排', requestedPoints: 3,
    });
    assert.equal(beforeSetup.status, 409);
    assert.equal((await beforeSetup.json()).error.code, 'STATION_NOT_INITIALIZED');

    const wifeToken = tokenFor(pair.wifeId);
    await request(baseUrl, wifeToken, 'POST', '/api/v1/station/initialize', { initialScore: 50 });
    const invalidPoints = await request(baseUrl, husbandToken, 'POST', '/api/v1/events/positive', {
      content: '主动承担了今天的家务安排', requestedPoints: 4,
    });
    assert.equal(invalidPoints.status, 400);
    assert.equal((await invalidPoints.json()).error.code, 'INVALID_REQUESTED_POINTS');

    const wifeSubmission = await request(baseUrl, wifeToken, 'POST', '/api/v1/events/positive', {
      content: '我不应该代替他提交行动记录', requestedPoints: 3,
    });
    assert.equal(wifeSubmission.status, 403);
    assert.equal((await wifeSubmission.json()).error.code, 'HUSBAND_ONLY');
  });
});

test('a two-character action with a photo is stored and visible to both members', async () => {
  await withApi(async ({ baseUrl, pair, tokenFor }) => {
    const wifeToken = tokenFor(pair.wifeId);
    const husbandToken = tokenFor(pair.husbandId);
    await request(baseUrl, wifeToken, 'POST', '/api/v1/station/initialize', { initialScore: 70 });
    const photoDataUrl = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';

    const submitted = await request(baseUrl, husbandToken, 'POST', '/api/v1/events/positive', {
      content: '洗碗',
      requestedPoints: 1,
      photoDataUrl,
    });
    assert.equal(submitted.status, 201);
    const event = (await submitted.json()).event;
    assert.equal(event.hasPhoto, true);

    const photo = await request(baseUrl, wifeToken, 'GET', `/api/v1/events/${event.id}/photo`);
    assert.equal(photo.status, 200);
    assert.equal(photo.headers.get('content-type'), 'image/png');
    assert.ok((await photo.arrayBuffer()).byteLength > 0);
  });
});
