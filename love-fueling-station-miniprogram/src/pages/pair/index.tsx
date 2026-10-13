import { navigateTo, setClipboardData, showToast, switchTab, useRouter, useShareAppMessage } from '@tarojs/taro';
import { Button, Image, Input, Text, View } from '@tarojs/components';
import { useState } from 'react';
import { scoreStatus } from '../../domain/relationship';
import { useRelationship } from '../../store/relationship-store';
import { cloudRelationshipApi, resolveCloudFileUrl } from '../../services/relationship-api';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import { inviteCodeFromLaunch, invitePath } from '../../domain/invite-link';
import './index.scss';

export default function PairPage() {
  const { connection, createInvite, acceptInvite, mode, profile, syncStatus } = useRelationship();
  usePageCloudRefresh();
  const router = useRouter();
  const sharedInvite = inviteCodeFromLaunch(router.params as Record<string, string | undefined>);
  const [displayName, setDisplayName] = useState(profile?.displayName === '未命名的伴侣' ? '' : profile?.displayName || '');
  const [inviteCode, setInviteCode] = useState(sharedInvite);
  const [createdCode, setCreatedCode] = useState<string | null>(null);
  const [miniCodeUrl, setMiniCodeUrl] = useState<string | null>(null);
  const [creatorScore, setCreatorScore] = useState('70');
  const [acceptedScore, setAcceptedScore] = useState('70');
  const [suggestedScore, setSuggestedScore] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [consented, setConsented] = useState(false);

  useShareAppMessage(() => ({
    title: '邀请你一起建立我们的爱意存折',
    path: createdCode ? invitePath(createdCode) : '/pages/pair/index',
  }));

  async function copyInvite(code: string) {
    try {
      await setClipboardData({ data: code });
      showToast({ title: '邀请码已复制，24小时内有效', icon: 'none' });
      return true;
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '复制失败，请再试一次', icon: 'none' });
      return false;
    }
  }

  async function createMiniCode() {
    if (!createdCode || busy) return;
    setBusy(true);
    try {
      const result = await cloudRelationshipApi.generateInviteMiniCode(createdCode);
      setMiniCodeUrl(await resolveCloudFileUrl(result.fileId));
      showToast({ title: '小程序码已生成，到期后会自动失效', icon: 'none' });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法生成小程序码', icon: 'none' });
    } finally { setBusy(false); }
  }

  async function create() {
    const initialScore = Number(creatorScore);
    if (busy || !consented || displayName.trim().length < 2 || !Number.isInteger(initialScore) || initialScore < 0 || initialScore > 100) return;
    setBusy(true);
    try {
      const invite = await createInvite(displayName, initialScore);
      setCreatedCode(invite.inviteCode);
      setInviteCode(invite.inviteCode);
      setMiniCodeUrl(null);
      await copyInvite(invite.inviteCode);
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法创建邀请', icon: 'none' });
    } finally { setBusy(false); }
  }

  async function accept() {
    const initialScore = Number(acceptedScore);
    if (busy || !consented || displayName.trim().length < 2 || inviteCode.trim().length < 6 || !Number.isInteger(initialScore) || initialScore < 0 || initialScore > 100) return;
    setBusy(true);
    try {
      const outcome = await acceptInvite(inviteCode, displayName, initialScore);
      showToast({ title: outcome.refreshed ? '共同空间已建立' : '配对已成功，页面暂未刷新', icon: outcome.refreshed ? 'success' : 'none' });
      switchTab({ url: '/pages/home/index' });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法建立共同空间', icon: 'none' });
    } finally { setBusy(false); }
  }

  async function loadSuggestedScore() {
    if (inviteCode.trim().length < 6 || busy) return;
    setBusy(true);
    try {
      const score = await cloudRelationshipApi.previewInvite(inviteCode);
      setSuggestedScore(score);
      setAcceptedScore(String(score));
      showToast({ title: `对方建议 ${score} 分，你可以修改`, icon: 'none' });
    } catch (error) {
      setSuggestedScore(null);
      showToast({ title: error instanceof Error ? error.message : '暂时无法读取邀请设置', icon: 'none' });
    } finally { setBusy(false); }
  }

  if (mode !== 'cloud') return <View className="page-shell pair-page"><Text className="page-title">等待 CloudBase 配置</Text><Text className="page-subtitle">填入 CloudBase 环境 ID 并部署云函数后，这里会启用微信身份配对。</Text></View>;
  if (syncStatus === 'loading') return <View className="page-shell pair-page"><Text className="page-title">正在确认微信身份…</Text></View>;

  return <View className="page-shell pair-page">
    <Text className="page-title">建立共同空间</Text>
    <Text className="page-subtitle">一段关系只由两位明确同意的伴侣组成；扫码或收到邀请码不会自动配对。</Text>
    <View className="pair-card surface">
      <Text className="input-label">你希望对方看到的称呼</Text>
      <Input className="pair-input" maxlength={20} value={displayName} onInput={(event) => setDisplayName(event.detail.value)} placeholder="例如：小满" />
    </View>
    <View className="pair-card surface">
      <Text className="section-title">共享前请确认</Text>
      <Text className="pair-copy">共同空间内容会向两位伴侣展示。经授权的运维或安全人员在故障、安全事件或法律义务所必需时，理论上也可能访问原始数据；应限制权限并留存审计。业务数据可免费导出，也可申请删除。</Text>
      <Button className={consented ? 'consent-button is-active' : 'consent-button'} onClick={() => setConsented(!consented)}>{consented ? '✓ 我已阅读并同意隐私说明' : '阅读后，点此确认同意'}</Button>
      <Button className="privacy-link" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>查看完整的数据与隐私说明</Button>
    </View>
    <View className="pair-card surface">
      <Text className="section-title">我来创建邀请</Text>
      <Text className="pair-copy">先由你提出一个初始爱意分数；受邀者在确认配对时可以修改，并以对方确认的数值为共同起点。邀请码仅使用一次，有效期 24 小时。</Text>
      <Text className="score-label">我建议的初始分数</Text>
      <Input className="pair-input score-input" maxlength={3} type="number" value={creatorScore} onInput={(event) => setCreatorScore(event.detail.value.replace(/[^0-9]/g, ''))} />
      <Text className="score-status">{Number.isInteger(Number(creatorScore)) && Number(creatorScore) >= 0 && Number(creatorScore) <= 100 ? scoreStatus(Number(creatorScore)).title : '请输入 0-100 的整数'}</Text>
      {createdCode ? <Text className="invite-code">{createdCode}</Text> : null}
      {createdCode ? <View className="invite-actions"><Button className="soft-button" disabled={busy} onClick={() => void copyInvite(createdCode)}>重新复制邀请码</Button><Button className="outline-button" openType="share">分享给对方</Button></View> : null}
      {createdCode ? <Button className="soft-button mini-code-button" disabled={busy} onClick={createMiniCode}>生成可扫码的小程序码</Button> : null}
      {miniCodeUrl ? <View className="mini-code-card"><Image className="mini-code-image" mode="widthFix" src={miniCodeUrl} /><Text>对方扫码后仍需确认初始分数，才会完成配对。</Text></View> : null}
      <Button className="primary-button" disabled={!consented || displayName.trim().length < 2 || !Number.isInteger(Number(creatorScore)) || Number(creatorScore) < 0 || Number(creatorScore) > 100 || busy} onClick={create}>{busy ? '正在创建…' : createdCode ? '重新生成邀请码' : '创建并复制邀请码'}</Button>
    </View>
    <View className="pair-card surface">
      <Text className="section-title">我来接受邀请</Text>
      <Input className="pair-input" maxlength={200} value={inviteCode} onInput={(event) => { setInviteCode(event.detail.value); setSuggestedScore(null); }} placeholder="粘贴对方发来的邀请码" />
      <Button className="soft-button pair-preview" disabled={inviteCode.trim().length < 6 || busy} onClick={loadSuggestedScore}>读取对方建议的初始分数</Button>
      <Text className="score-label">我确认后的共同初始分数</Text>
      <Input className="pair-input score-input" maxlength={3} type="number" value={acceptedScore} onInput={(event) => setAcceptedScore(event.detail.value.replace(/[^0-9]/g, ''))} />
      <Text className="score-status">{suggestedScore === null ? '受邀者可以修改该数值；确认后它会成为默认分数。' : `对方建议 ${suggestedScore} 分；你当前确认 ${acceptedScore || '—'} 分。`}</Text>
      <Button className="outline-button" disabled={!consented || displayName.trim().length < 2 || inviteCode.trim().length < 6 || !Number.isInteger(Number(acceptedScore)) || Number(acceptedScore) < 0 || Number(acceptedScore) > 100 || busy} onClick={accept}>{busy ? '正在确认…' : '确认分数并建立共同空间'}</Button>
    </View>
    <View className="pair-safety"><Text>任何一方都可以随时退出共同空间；退出后将立即停止对方访问。</Text></View>
  </View>;
}
