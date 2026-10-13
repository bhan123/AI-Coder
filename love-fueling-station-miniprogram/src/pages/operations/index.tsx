import { Button, Text, View } from '@tarojs/components';
import { useEffect, useState } from 'react';
import { loadOperationsMetrics } from '../../services/relationship-api';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import './index.scss';

type Metrics = Awaited<ReturnType<typeof loadOperationsMetrics>>;

export default function OperationsPage() {
  usePageCloudRefresh();
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  async function refreshMetrics() {
    if (loading) return;
    setLoading(true); setError(null);
    try { setMetrics(await loadOperationsMetrics()); } catch (reason) { setError(reason instanceof Error ? reason.message : '无法读取运营指标。'); } finally { setLoading(false); }
  }
  useEffect(() => { void refreshMetrics(); }, []);
  return <View className="page-shell operations-page">
    <Text className="page-title">最小化运营指标</Text>
    <Text className="page-subtitle">仅统计运行健康度，不展示任何伴侣正文、称呼或身份标识。</Text>
    {error ? <View className="operations-note surface"><Text>{error}</Text><Text>此页面仅向 CloudBase 环境变量 ADMIN_OPENIDS 中的运营人员开放。</Text></View> : null}
    {metrics ? <View className="metrics-grid">
      <View className="metric-card surface"><Text>{metrics.activeCouples}</Text><Text>活跃共同空间</Text></View>
      <View className="metric-card surface"><Text>{metrics.relationshipRecords}</Text><Text>关系记录总数</Text></View>
      <View className="metric-card surface"><Text>{metrics.pendingNotifications}</Text><Text>待发送提醒</Text></View>
      <View className="metric-card surface"><Text>{metrics.notificationAttention}</Text><Text>需处理的通知</Text></View>
      <View className="metric-card surface"><Text>{metrics.privacyCleanupBacklog}</Text><Text>待清理隐私请求</Text></View>
      <Text className="metric-time">更新于 {new Date(metrics.generatedAt).toLocaleString('zh-CN')}</Text>
    </View> : null}
    <Button className="soft-button" loading={loading} onClick={refreshMetrics}>刷新指标</Button>
  </View>;
}
