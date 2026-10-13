import assert from 'node:assert/strict';
import test from 'node:test';
import { inviteCodeFromLaunch, invitePath } from '../src/domain/invite-link';
import { resolveSpaceAccess } from '../src/domain/space-access';

test('共同空间访问门禁先拦截同步、隐私和配对状态', () => {
  assert.equal(resolveSpaceAccess({ mode: 'cloud', connection: 'paired', privacyRequired: false, syncStatus: 'loading' }), 'loading');
  assert.equal(resolveSpaceAccess({ mode: 'cloud', connection: 'paired', privacyRequired: true, syncStatus: 'ready' }), 'privacy_required');
  assert.equal(resolveSpaceAccess({ mode: 'cloud', connection: 'unpaired', privacyRequired: false, syncStatus: 'ready' }), 'pair_required');
  assert.equal(resolveSpaceAccess({ mode: 'local-preview', connection: 'unpaired', privacyRequired: true, syncStatus: 'error' }), 'ready');
});

test('邀请分享链接与小程序码 scene 都能还原一次性邀请码', () => {
  const code = 'AbCd.efghijklmnop';
  assert.equal(inviteCodeFromLaunch({ invite: code }), code);
  assert.equal(inviteCodeFromLaunch({ scene: `i=${encodeURIComponent(code)}&v=1` }), code);
  assert.match(invitePath(code), /invite=AbCd.efghijklmnop/);
});
