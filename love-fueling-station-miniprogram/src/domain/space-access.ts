export type SpaceConnection = 'unpaired' | 'paired' | 'deletion_pending';
export type SpaceAccess = 'ready' | 'loading' | 'sync_error' | 'privacy_required' | 'deletion_pending' | 'pair_required';

/** 前端访问门禁的纯规则；云函数仍是最终权限边界。 */
export function resolveSpaceAccess(input: {
  mode: 'cloud' | 'local-preview';
  connection: SpaceConnection;
  privacyRequired: boolean;
  syncStatus: 'loading' | 'ready' | 'error';
}): SpaceAccess {
  if (input.mode === 'local-preview') return 'ready';
  if (input.syncStatus === 'loading') return 'loading';
  if (input.syncStatus === 'error') return 'sync_error';
  if (input.privacyRequired) return 'privacy_required';
  if (input.connection === 'deletion_pending') return 'deletion_pending';
  return input.connection === 'paired' ? 'ready' : 'pair_required';
}
