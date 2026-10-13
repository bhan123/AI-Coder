import { navigateTo } from '@tarojs/taro';
import { Button, Text, View } from '@tarojs/components';
import { PropsWithChildren } from 'react';
import { resolveSpaceAccess } from '../domain/space-access';
import { useRelationship } from '../store/relationship-store';

/** 让 tab 页在前端直接说明下一步，而不是把未配对请求送到云函数后才报错。 */
export function SpaceAccessGate({ children }: PropsWithChildren) {
  const { mode, connection, privacyNotice, syncError, syncStatus, refresh } = useRelationship();
  const access = resolveSpaceAccess({ mode, connection: connection.status, privacyRequired: privacyNotice.required, syncStatus });
  if (access === 'ready') return <>{children}</>;
  if (access === 'loading') return <View className="page-shell access-gate"><Text className="page-title">正在同步共同空间…</Text></View>;
  if (access === 'sync_error') return <View className="page-shell access-gate"><Text className="page-title">暂时无法连接共同空间</Text><Text className="page-subtitle">{syncError || '请稍后重试。'}</Text><Button className="primary-button" onClick={() => void refresh()}>重新同步</Button></View>;
  if (access === 'privacy_required') return <View className="page-shell access-gate"><Text className="page-title">请先确认隐私说明</Text><Text className="page-subtitle">确认最新版说明后，才会加载共同空间中的记录。</Text><Button className="primary-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>阅读并确认</Button></View>;
  if (access === 'deletion_pending') return <View className="page-shell access-gate"><Text className="page-title">共同空间已停止共享</Text><Text className="page-subtitle">删除流程正在进行。你可以在“数据与隐私”页查看状态。</Text><Button className="soft-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>查看数据与隐私</Button></View>;
  if (access === 'pair_required') return <View className="page-shell access-gate"><Text className="page-title">先建立共同空间</Text><Text className="page-subtitle">创建或接受一次性邀请后，才可以记录、回应和共同确认。</Text><Button className="primary-button" onClick={() => navigateTo({ url: '/pages/pair/index' })}>去建立共同空间</Button></View>;
  return <>{children}</>;
}
