import { navigateTo, switchTab } from '@tarojs/taro';
import { Button, Text, View } from '@tarojs/components';
import { PendingCard } from '../../components/PendingCard';
import { SafetyNotice } from '../../components/SafetyNotice';
import { scoreStatus } from '../../domain/relationship';
import { useRelationship } from '../../store/relationship-store';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import { releaseChannel, releaseVersion } from '../../config/release';
import './index.scss';

export default function HomePage() {
  const { state, pending, connection, mode, privacyNotice, syncError, syncStatus, refresh, lastSyncedAt } = useRelationship();
  usePageCloudRefresh();
  const status = scoreStatus(state.score);

  if (mode === 'cloud' && syncStatus === 'loading') return <View className="page-shell home-page"><Text className="home-greeting">正在同步你们的共同空间…</Text></View>;
  if (mode === 'cloud' && syncStatus === 'error') return <View className="page-shell home-page"><Text className="home-greeting">暂时无法连接共同空间</Text><Text className="page-subtitle">{syncError || '请稍后重试。'}</Text><Button className="primary-button" onClick={() => void refresh()}>重新同步</Button></View>;
  if (mode === 'cloud' && connection.status === 'deletion_pending') return (
    <View className="page-shell home-page">
      <View className="brand-row"><Text className="brand-mark">☼</Text><Text className="brand-name">爱意存折</Text></View>
      <Text className="home-greeting">个人数据删除已受理</Text>
      <View className="temperature-card surface"><Text className="temperature-title">共同空间已经停止共享</Text><Text className="temperature-description">预计在 {new Date(connection.deleteAfter).toLocaleDateString('zh-CN')} 前完成业务库删除。详情可在数据与隐私页查看。</Text></View>
      <Button className="soft-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>查看数据与隐私</Button>
    </View>
  );
  if (mode === 'cloud' && connection.status === 'paired' && privacyNotice.required) return (
    <View className="page-shell home-page">
      <View className="brand-row"><Text className="brand-mark">☼</Text><Text className="brand-name">爱意存折</Text></View>
      <Text className="home-greeting">隐私说明已经更新</Text>
      <View className="temperature-card surface"><Text className="temperature-title">重新确认后继续进入共同空间</Text><Text className="temperature-description">更新期间不会加载双方记录。请先阅读最新版说明，再决定是否继续使用。</Text></View>
      <Button className="primary-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>阅读并确认</Button>
    </View>
  );
  if (mode === 'cloud' && connection.status !== 'paired') return (
    <View className="page-shell home-page">
      <View className="brand-row"><Text className="brand-mark">☼</Text><Text className="brand-name">爱意存折</Text><Text className="private-note">双方共享</Text></View>
      <Text className="home-greeting">先建立属于你们的共同空间</Text>
      <View className="temperature-card surface"><Text className="temperature-title">双方确认后才会开始记录</Text><Text className="temperature-description">创建一次性邀请，或接受对方发来的邀请码。打开邀请码不会自动配对。</Text></View>
      <Button className="primary-button" onClick={() => navigateTo({ url: '/pages/pair/index' })}>建立共同空间</Button>
      <Button className="soft-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>先了解数据与隐私</Button>
      <SafetyNotice />
    </View>
  );

  return (
    <View className="page-shell home-page">
      <View className="brand-row"><Text className="brand-mark">☼</Text><Text className="brand-name">爱意存折</Text><Text className="private-note">双方共享</Text></View>
      <Text className="home-greeting">今天，也认真看见彼此</Text>
      {mode === 'cloud' ? <View className="sync-row"><Text>{lastSyncedAt ? `已同步 ${new Date(lastSyncedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '等待首次同步'}</Text><Button className="sync-button" onClick={() => void refresh()}>刷新</Button></View> : null}

      <View className="temperature-card surface">
        <Text className="temperature-eyebrow">爱意分数</Text>
        <Text className="temperature-value">{state.score}</Text>
        <Text className="temperature-title">{status.title}</Text>
        <Text className="temperature-description">{status.description}</Text>
      </View>

      <View className="home-actions">
        <Button className="primary-button" onClick={() => switchTab({ url: '/pages/record/index' })}>记录一件事</Button>
        <Button className="soft-button" onClick={() => switchTab({ url: '/pages/agreements/index' })}>看看我们的约定</Button>
      </View>

      <View className="section-heading"><Text>等待我们处理</Text><Text>{pending.length} 件</Text></View>
      {pending.length > 0 ? pending.slice(0, 2).map((record) => (
        <PendingCard key={record.id} record={record} viewerId={state.viewerId} onRespond={() => switchTab({ url: '/pages/history/index' })} />
      )) : <View className="surface empty-state"><Text>此刻没有需要立刻处理的记录。慢一点，也可以。</Text></View>}

      <View className="principle-card">
        <Text className="principle-number">01</Text>
        <View><Text className="principle-title">记录感受，不给彼此定罪</Text><Text className="principle-copy">行动可以被看见，感受值得被回应；温度不会兑换原谅。</Text></View>
      </View>
      <SafetyNotice />
      <Button className="soft-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>数据导出、删除与隐私说明</Button>
      <Text className="release-note">{releaseVersion} · {releaseChannel}</Text>
    </View>
  );
}
