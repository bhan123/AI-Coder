export function invitePath(inviteCode: string) {
  return `/pages/pair/index?invite=${encodeURIComponent(inviteCode)}`;
}

export function inviteCodeFromLaunch(params: Record<string, string | undefined>) {
  const raw = params.invite || params.scene;
  if (!raw) return '';
  const value = decodeURIComponent(raw);
  if (params.scene) {
    const match = value.split('&').find((item) => item.startsWith('i='));
    return match ? match.slice(2) : '';
  }
  return value;
}
