import { showToast } from '@tarojs/taro';
import { Button, Input, Text, View } from '@tarojs/components';
import { useMemo, useState } from 'react';
import { PositivePoints, RelationshipRecord, partnerName } from '../../domain/relationship';
import { useRelationship } from '../../store/relationship-store';
import { SpaceAccessGate } from '../../components/SpaceAccessGate';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import { RecordAttachments } from '../../components/RecordAttachments';
import './index.scss';

const FILTERS = [
  { id: 'month', label: '近1月', days: 30 },
  { id: 'quarter', label: '近3月', days: 90 },
  { id: 'all', label: '全部', days: null },
] as const;
const POINTS: PositivePoints[] = [1, 3, 5];

function formatTime(date: string) { return new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(date)); }
function recordMeta(record: RelationshipRecord) {
  if (record.kind === 'care') return record.status === 'approved' ? `已通过，+${record.effectivePoints}分` : record.status === 'rejected' ? '已驳回，本次不加分' : `等待对方审批（建议+${record.requestedPoints}）`;
  if (record.kind === 'feeling') return `${record.status === 'responded' ? '已认真回应' : '等待认真回应'} · 已扣${Math.abs(record.effectivePoints)}分`;
  if (record.kind === 'score_adjustment') return record.status === 'confirmed' ? `双方确认，分数调整为 ${record.proposedScore}` : record.status === 'declined' ? '调分申请未通过' : `等待双方确认调整为 ${record.proposedScore}`;
  return record.status === 'confirmed' ? '双方已确认的约定' : record.status === 'declined' ? '这条约定暂不启用' : '等待双方共同确认';
}

export default function HistoryPage() {
  const { state, respond, reviewCare, decideScoreAdjustment, hasMoreRecords, loadMoreRecords, mode } = useRelationship();
  usePageCloudRefresh();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('month');
  const [replyingId, setReplyingId] = useState<string | null>(null);
  const [reviewingId, setReviewingId] = useState<string | null>(null);
  const [reply, setReply] = useState('');
  const [reviewPoints, setReviewPoints] = useState<PositivePoints>(3);
  const [loadingMore, setLoadingMore] = useState(false);
  const visibleRecords = useMemo(() => {
    const selected = FILTERS.find((item) => item.id === filter);
    if (!selected?.days) return state.records;
    const cutoff = Date.now() - selected.days * 86400000;
    return state.records.filter((item) => new Date(item.createdAt).getTime() >= cutoff);
  }, [filter, state.records]);

  function canReply(record: RelationshipRecord) { return record.kind === 'feeling' && record.authorId !== state.viewerId && record.status === 'awaiting_response'; }
  function canReviewCare(record: RelationshipRecord) { return record.kind === 'care' && record.authorId !== state.viewerId && record.status === 'pending'; }
  function canDecideAdjustment(record: RelationshipRecord) { return record.kind === 'score_adjustment' && record.authorId !== state.viewerId && record.status === 'pending'; }
  async function submitReply(recordId: string) {
    try { const outcome = await respond(recordId, reply); setReply(''); setReplyingId(null); showToast({ title: outcome.refreshed ? '回应已保存' : '回应已保存到云端，页面暂未刷新', icon: 'none' }); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法保存', icon: 'none' }); }
  }
  async function decideCare(recordId: string, decision: 'approved' | 'rejected') {
    try { const outcome = await reviewCare(recordId, decision, reviewPoints); setReviewingId(null); showToast({ title: outcome.refreshed ? (decision === 'approved' ? `已通过，+${reviewPoints}分` : '已驳回，本次不加分') : '审批已保存到云端，页面暂未刷新', icon: 'none' }); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法审批', icon: 'none' }); }
  }
  async function decideAdjustment(recordId: string, accept: boolean) {
    try { const outcome = await decideScoreAdjustment(recordId, accept); showToast({ title: outcome.refreshed ? (accept ? '已确认手动调分' : '已驳回手动调分') : '决定已保存到云端，页面暂未刷新', icon: 'none' }); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法处理', icon: 'none' }); }
  }
  async function loadMore() { if (loadingMore) return; setLoadingMore(true); try { await loadMoreRecords(); } catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法加载更多', icon: 'none' }); } finally { setLoadingMore(false); } }

  return <SpaceAccessGate><View className="page-shell history-page">
    <Text className="page-title">我们的记录</Text>
    <Text className="page-subtitle">行动由对方审批，感受直接扣分；每一次变化都留在共同历史里。</Text>
    <View className="history-filter surface">{FILTERS.map((item) => <Button className={filter === item.id ? 'filter-item is-active' : 'filter-item'} key={item.id} onClick={() => setFilter(item.id)}>{item.label}</Button>)}</View>
    <View className="history-note"><Text>行动审批可以调整分数</Text><Text>手动调分必须双方确认</Text></View>
    <View className="timeline">
      {visibleRecords.map((record) => <View className={`timeline-item type-${record.kind}`} key={record.id}><View className="timeline-dot" /><View className="timeline-card surface">
        <View className="timeline-meta"><Text>{formatTime(record.createdAt)}</Text><Text>{partnerName(record.authorId, state.viewerId)}{record.kind === 'score_adjustment' ? '申请调分' : '记录'}</Text></View>
        {record.kind === 'rule' ? <Text className="timeline-title">{record.title}</Text> : <Text className="timeline-title">{record.content}</Text>}
        {record.kind === 'rule' ? <Text className="timeline-detail">{record.content}</Text> : null}
        <RecordAttachments attachments={'attachments' in record ? record.attachments : undefined} />
        <Text className="timeline-status">{recordMeta(record)}</Text>
        {record.kind === 'care' ? <Text className="timeline-detail">申请加分：+{record.requestedPoints}</Text> : null}
        {'response' in record && record.response ? <View className="response-box"><Text>回应</Text><Text>{record.response}</Text></View> : null}
        {canReply(record) ? <View className="reply-area">{replyingId === record.id ? <><Input className="reply-input" maxlength={300} onInput={(event) => setReply(event.detail.value)} placeholder="写下一句具体回应" value={reply} /><View className="reply-actions"><Button className="outline-button" onClick={() => { setReply(''); setReplyingId(null); }}>先不写</Button><Button className="primary-button" disabled={reply.trim().length < 2} onClick={() => submitReply(record.id)}>确认回应</Button></View></> : <Button className="outline-button reply-open" onClick={() => setReplyingId(record.id)}>认真回应</Button>}</View> : null}
        {record.kind === 'care' && canReviewCare(record) ? <View className="review-area">{reviewingId === record.id ? <><Text className="review-label">本次实际加分</Text><View className="review-points">{POINTS.map((points) => <Button key={points} className={reviewPoints === points ? 'review-point is-active' : 'review-point'} onClick={() => setReviewPoints(points)}>+{points}</Button>)}</View><View className="reply-actions"><Button className="outline-button" onClick={() => decideCare(record.id, 'rejected')}>驳回</Button><Button className="primary-button" onClick={() => decideCare(record.id, 'approved')}>通过并加分</Button></View></> : <Button className="primary-button reply-open" onClick={() => { setReviewingId(record.id); setReviewPoints(record.requestedPoints); }}>审批这份行动</Button>}</View> : null}
        {canDecideAdjustment(record) ? <View className="reply-actions"><Button className="outline-button" onClick={() => decideAdjustment(record.id, false)}>驳回调分</Button><Button className="primary-button" onClick={() => decideAdjustment(record.id, true)}>共同确认</Button></View> : null}
      </View></View>)}
      {visibleRecords.length === 0 ? <View className="surface empty-state"><Text>这段时间还没有记录。</Text></View> : null}
      {mode === 'cloud' && hasMoreRecords ? <Button className="soft-button" loading={loadingMore} onClick={loadMore}>加载更多历史记录</Button> : null}
    </View>
  </View></SpaceAccessGate>;
}
