import { setClipboardData, showModal, showToast } from '@tarojs/taro';
import { Button, Text, View } from '@tarojs/components';
import { useEffect, useState } from 'react';
import { cloudRelationshipApi } from '../../services/relationship-api';
import { requestPartnerNotification } from '../../services/relationship-api';
import { useRelationship } from '../../store/relationship-store';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import { partnerNotificationTemplateId, partnerNotificationsConfigured } from '../../config/notifications';
import './index.scss';

type PendingRequest = { id: string; type: 'space_deletion'; createdAt: string; expiresAt: string };

export default function PrivacyPage() {
  const { mode, connection, privacyNotice, acceptPrivacyNotice, refresh } = useRelationship();
  usePageCloudRefresh();
  const [requests, setRequests] = useState<PendingRequest[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [exportCursor, setExportCursor] = useState<string | null | undefined>(undefined);
  const [exportSegmentCount, setExportSegmentCount] = useState(0);
  const coupleId = connection.status === 'paired' ? connection.coupleId : null;

  useEffect(() => {
    if (mode !== 'cloud' || !coupleId) return;
    let active = true;
    void cloudRelationshipApi.getPrivacyStatus()
      .then((value) => { if (active) setRequests(value.requests); })
      .catch(() => { if (active) setRequests([]); });
    return () => { active = false; };
  }, [coupleId, mode]);

  async function execute(key: string, operation: () => Promise<unknown>, success: string) {
    if (busy) return;
    setBusy(key);
    try {
      await operation();
      const refreshed = await refresh();
      showToast({ title: refreshed ? success : `${success}，页面暂未刷新`, icon: 'none' });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法完成操作', icon: 'none' });
    } finally {
      setBusy(null);
    }
  }

  async function exportData() {
    if (busy) return;
    setBusy('export');
    try {
      const data = await cloudRelationshipApi.exportMyData();
      await setClipboardData({ data: JSON.stringify(data, null, 2) });
      showModal({ title: '原始数据已复制', content: '已生成仅包含本人数据的免费 JSON 副本并复制到剪贴板。请粘贴到你信任的位置妥善保存。', showCancel: false });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法导出', icon: 'none' });
    } finally {
      setBusy(null);
    }
  }

  async function exportNextSegment() {
    if (busy) return;
    setBusy('export-segment');
    try {
      const result = await cloudRelationshipApi.exportMyDataSegment(exportCursor || null);
      const number = exportSegmentCount + 1;
      await setClipboardData({ data: JSON.stringify({ exportedAt: result.exportedAt, snapshotAt: result.snapshotAt, segmentNumber: number, ...result.segment }, null, 2) });
      setExportSegmentCount(number);
      setExportCursor(result.nextCursor);
      showModal({ title: `第 ${number} 段已复制`, content: result.nextCursor ? '这一段关系记录已复制到剪贴板。请保存后继续导出下一段。' : '这是最后一段，关系记录分段导出已完成。', showCancel: false });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法分段导出', icon: 'none' });
    } finally {
      setBusy(null);
    }
  }

  async function acceptUpdatedPrivacy() {
    if (busy) return;
    setBusy('privacy-consent');
    try {
      const outcome = await acceptPrivacyNotice();
      showToast({ title: outcome.refreshed ? '已确认最新版隐私说明' : '确认已保存，页面暂未刷新', icon: 'none' });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法保存确认', icon: 'none' });
    } finally {
      setBusy(null);
    }
  }

  async function enablePartnerNotifications() {
    if (busy) return;
    setBusy('notifications');
    try {
      const outcome = await requestPartnerNotification(partnerNotificationTemplateId);
      showToast({ title: outcome.accepted ? '已获得一次提醒授权' : '你暂未同意提醒', icon: 'none' });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法设置提醒', icon: 'none' });
    } finally {
      setBusy(null);
    }
  }

  async function requestPersonalDeletion() {
    const decision = await showModal({
      title: '删除本人资料',
      content: '申请后会立即停止共同空间共享，且不可撤销。业务库数据计划在7天内清理；应用自行创建的备份最迟30天清理。请先导出需要保留的数据。',
      confirmText: '确认申请',
      confirmColor: '#c74835',
    });
    if (decision.confirm) await execute('personal-delete', () => cloudRelationshipApi.requestPersonalDeletion(), '删除申请已受理');
  }

  async function requestSpaceDeletion() {
    const decision = await showModal({
      title: '申请删除共同空间',
      content: '共同空间包含双方内容，需要另一位伴侣确认后才会关闭并进入删除流程。',
      confirmText: '发起申请',
      confirmColor: '#c74835',
    });
    if (decision.confirm) await execute('space-delete', () => cloudRelationshipApi.requestSpaceDeletion(), '已等待对方确认删除');
  }

  return (
    <View className="page-shell privacy-page">
      <Text className="page-title">数据与隐私</Text>
      <Text className="page-subtitle">先把谁能看、保存多久、如何带走和删除说清楚，再决定是否共享亲密关系内容。</Text>

      {mode === 'cloud' && privacyNotice.required ? (
        <View className="privacy-card privacy-consent-card surface">
          <Text className="privacy-heading">隐私说明已更新</Text>
          <Text className="privacy-copy">当前版本：{privacyNotice.version}。重新确认前，系统不会加载共同空间中的关系记录。</Text>
          <Button className="primary-button" loading={busy === 'privacy-consent'} disabled={Boolean(busy)} onClick={acceptUpdatedPrivacy}>我已阅读并同意最新版说明</Button>
        </View>
      ) : null}

      <View className="privacy-card surface">
        <Text className="privacy-heading">谁能看到</Text>
        <Text className="privacy-copy">产品界面只向共同空间内的两位伴侣展示内容。CloudBase 管理员以及经授权的开发、运维或安全人员，在排障、安全事件或法律义务所必需时，理论上仍可能接触原始数据。正式运营必须采用最小权限，并对管理访问留痕。</Text>
      </View>

      <View className="privacy-card surface">
        <Text className="privacy-heading">保存与删除</Text>
        <Text className="privacy-copy">正常使用期间，记录持续保存，方便双方查看完整历史。本人删除会删除本人创建的记录，并擦除本人写在对方记录中的回应、确认及关联标识；本人删除或双方确认删除共同空间后，立即停止共享，业务主库计划在7天内删除；应用自行生成的备份或临时副本最迟30天清理。依法必须保留的安全审计信息会做最小化处理。</Text>
      </View>

      <View className="privacy-card surface">
        <Text className="privacy-heading">导出范围</Text>
        <Text className="privacy-copy">“导出我的原始数据”只包含本人资料、本人创建的记录，以及本人写在对方记录中的回应或约定决定；退出共同空间后也不会重新取得对方正文。一次复制上限为 512 KiB；“分段导出我的关系记录”会按稳定快照逐段复制本人记录与本人贡献，不会静默截断。完整共同空间导出暂未开放，后续如提供必须由双方分别确认。</Text>
      </View>

      <View className="privacy-card surface">
        <Text className="privacy-heading">内容安全检查</Text>
        <Text className="privacy-copy">在你已同意当前隐私说明且具备共同空间权限后，称呼、行动、感受、回应和约定文本会提交给微信内容安全接口进行自动检测。检测仅用于决定内容能否保存；未通过时不会写入，不用于评价任何人的人格或关系。</Text>
      </View>

      <View className="privacy-card surface">
        <Text className="privacy-heading">关系动态提醒</Text>
        <Text className="privacy-copy">你可以自愿授权一次微信服务通知，用于接收对方提交行动、回应感受或确认约定等提醒。授权只对应一条消息，不会持续骚扰；每次需要时都由你主动重新授权。</Text>
        {mode === 'cloud' && partnerNotificationsConfigured ? <Button className="soft-button" loading={busy === 'notifications'} disabled={Boolean(busy)} onClick={enablePartnerNotifications}>授权接收一条提醒</Button> : <Text className="privacy-pending">当前体验环境尚未配置微信订阅消息模板，认证完成后可开启。</Text>}
      </View>

      <View className="privacy-card surface">
        <Text className="privacy-heading">请避免填写</Text>
        <Text className="privacy-copy">身份证号、银行卡、精确住址、医疗诊断、未成年人信息，以及任何并非你有权提供的第三方秘密。本工具不适合处理控制、威胁或暴力关系，也不是婚姻治疗。</Text>
      </View>

      {mode !== 'cloud' ? <View className="privacy-card surface"><Text className="privacy-heading">当前是本地体验模式</Text><Text className="privacy-copy">尚未连接 CloudBase，不会启用云端导出和删除操作。正式试用前仍需部署隐私清理任务并配置微信隐私保护指引。</Text></View> : (
        <View className="privacy-actions">
          <Button className="primary-button" loading={busy === 'export'} disabled={Boolean(busy)} onClick={exportData}>免费导出我的原始数据</Button>
          <Button className="soft-button" loading={busy === 'export-segment'} disabled={Boolean(busy) || exportCursor === null} onClick={exportNextSegment}>{exportCursor === null && exportSegmentCount > 0 ? '关系记录已全部导出' : exportSegmentCount > 0 ? `继续导出第 ${exportSegmentCount + 1} 段` : '分段导出我的关系记录'}</Button>
          {connection.status === 'unpaired' ? <Button className="soft-button" disabled={Boolean(busy)} onClick={() => execute('cancel-invite', () => cloudRelationshipApi.cancelInvite(), '有效邀请已撤回')}>撤回我创建的邀请</Button> : null}
          {connection.status === 'paired' ? <Button className="outline-button" disabled={Boolean(busy)} onClick={requestSpaceDeletion}>申请删除共同空间</Button> : null}
          {requests.map((request) => <View className="privacy-request surface" key={request.id}><Text>对方申请删除共同空间</Text><Text>确认后将立即停止双方访问，并进入删除流程。本申请会在 {new Date(request.expiresAt).toLocaleDateString('zh-CN')} 自动失效。</Text><Button className="outline-button" disabled={Boolean(busy)} onClick={() => execute(`confirm-${request.id}`, () => cloudRelationshipApi.confirmSpaceDeletion(request.id), '共同空间已进入删除流程')}>确认共同删除</Button></View>)}
          {connection.status !== 'deletion_pending' ? <Button className="danger-button" disabled={Boolean(busy)} onClick={requestPersonalDeletion}>删除本人资料并停止共享</Button> : <Text className="privacy-pending">删除申请已受理，预计在 {new Date(connection.deleteAfter).toLocaleDateString('zh-CN')} 前完成业务库清理。</Text>}
        </View>
      )}

      <Text className="privacy-footnote">正式商业化前，还需要由实际运营主体补充主体名称、联系方式、第三方处理清单、投诉渠道和适用于具体业务的完整隐私政策。</Text>
    </View>
  );
}
