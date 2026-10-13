import { navigateTo, showModal, showToast, switchTab } from '@tarojs/taro';
import { Button, Input, Text, Textarea, View } from '@tarojs/components';
import { useState } from 'react';
import { SafetyNotice } from '../../components/SafetyNotice';
import { useRelationship } from '../../store/relationship-store';
import { SpaceAccessGate } from '../../components/SpaceAccessGate';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import './index.scss';

export default function AgreementsPage() {
  const { state, pending, proposeRule, confirmRule, proposeScoreAdjustment, decideScoreAdjustment, switchViewer, reset, mode, leaveSpace } = useRelationship();
  usePageCloudRefresh();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [score, setScore] = useState(String(state.score));
  const [scoreReason, setScoreReason] = useState('');
  const pendingRules = pending.filter((record) => record.kind === 'rule');
  const pendingAdjustments = pending.filter((record) => record.kind === 'score_adjustment');

  async function submitProposal() {
    try { const outcome = await proposeRule({ title, content }); showToast({ title: outcome.refreshed ? '已提出，等待双方确认' : '约定已保存到云端，页面暂未刷新', icon: 'none' }); setTitle(''); setContent(''); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法保存', icon: 'none' }); }
  }
  async function decide(ruleId: string, accept: boolean) {
    try { const outcome = await confirmRule(ruleId, accept); showToast({ title: outcome.refreshed ? (accept ? '约定已由双方确认' : '已暂不启用这条约定') : '决定已保存到云端，页面暂未刷新', icon: 'none' }); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法保存', icon: 'none' }); }
  }
  async function submitScoreAdjustment() {
    const proposedScore = Number(score);
    if (!Number.isInteger(proposedScore) || proposedScore < 0 || proposedScore > 100 || scoreReason.trim().length < 2) return;
    try { const outcome = await proposeScoreAdjustment(proposedScore, scoreReason); showToast({ title: outcome.refreshed ? '调分申请已提交，等待对方确认' : '调分申请已保存到云端，页面暂未刷新', icon: 'none' }); setScoreReason(''); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法提交', icon: 'none' }); }
  }
  async function decideAdjustment(recordId: string, accept: boolean) {
    try { const outcome = await decideScoreAdjustment(recordId, accept); showToast({ title: outcome.refreshed ? (accept ? '已确认手动调分' : '已驳回手动调分') : '决定已保存到云端，页面暂未刷新', icon: 'none' }); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法处理', icon: 'none' }); }
  }
  async function leave() {
    const decision = await showModal({ title: '退出共同空间', content: '退出后会立即停止双方继续访问这个共同空间。你仍可导出本人创建和贡献的数据，但不能重新取得对方内容；历史记录会保留到删除流程完成。', confirmText: '确认退出', confirmColor: '#c74835' });
    if (!decision.confirm) return;
    try { const outcome = await leaveSpace(); showToast({ title: outcome.refreshed ? '已退出共同空间' : '已退出，页面暂未刷新', icon: 'none' }); switchTab({ url: '/pages/home/index' }); }
    catch (error) { showToast({ title: error instanceof Error ? error.message : '暂时无法退出', icon: 'none' }); }
  }

  return <SpaceAccessGate><View className="page-shell agreements-page">
    <Text className="page-title">我们的约定</Text>
    <Text className="page-subtitle">行动审批和感受扣分会改变分数；除此之外的手动调分，必须由双方确认。</Text>
    <View className="principles surface">
      <View className="principle-row"><Text>01</Text><View><Text>行动由对方审批</Text><Text>可以通过、调整为 +1/+3/+5，或驳回。</Text></View></View>
      <View className="principle-row"><Text>02</Text><View><Text>感受会直接扣分</Text><Text>扣分后仍应认真回应，不把分数当成判决。</Text></View></View>
      <View className="principle-row"><Text>03</Text><View><Text>手动调分必须双方确认</Text><Text>任何一方都不能绕开对方直接修改当前分数。</Text></View></View>
    </View>

    {pendingAdjustments.length > 0 ? <View className="agreement-section"><Text className="section-title">等待确认的调分</Text>{pendingAdjustments.map((item) => <View className="rule-card surface" key={item.id}><Text className="rule-label">对方申请</Text><Text className="rule-title">将当前分数调整为 {item.proposedScore}</Text><Text className="rule-copy">{item.content}</Text><View className="rule-actions"><Button className="outline-button" onClick={() => decideAdjustment(item.id, false)}>驳回</Button><Button className="primary-button" onClick={() => decideAdjustment(item.id, true)}>共同确认</Button></View></View>)}</View> : null}
    {pendingRules.length > 0 ? <View className="agreement-section"><Text className="section-title">等待共同确认的约定</Text>{pendingRules.map((rule) => <View className="rule-card surface" key={rule.id}><Text className="rule-label">对方提出</Text><Text className="rule-title">{rule.title}</Text><Text className="rule-copy">{rule.content}</Text><View className="rule-actions"><Button className="outline-button" onClick={() => decide(rule.id, false)}>暂不启用</Button><Button className="primary-button" onClick={() => decide(rule.id, true)}>共同确认</Button></View></View>)}</View> : null}

    <View className="agreement-section"><Text className="section-title">申请手动调整分数</Text><Text className="proposal-tip">不会立即生效；需由另一位伴侣确认。日常行动与感受请从“记录”页提交。</Text><View className="proposal-form surface"><Text className="form-label">建议调整为</Text><View className="temperature-input-row"><Input maxlength={3} onInput={(event) => setScore(event.detail.value.replace(/[^0-9]/g, ''))} type="number" value={score} /><Text>分</Text></View><Text className="form-label">为什么需要调整</Text><Textarea autoHeight className="form-textarea" maxlength={300} onInput={(event) => setScoreReason(event.detail.value)} placeholder="写下双方能理解的原因或共识" value={scoreReason} /><Button className="primary-button proposal-submit" disabled={!Number.isInteger(Number(score)) || Number(score) < 0 || Number(score) > 100 || scoreReason.trim().length < 2} onClick={submitScoreAdjustment}>提交给对方确认</Button></View></View>
    <View className="agreement-section"><Text className="section-title">提出一条共同约定</Text><Text className="proposal-tip">它不会立刻生效；提交后，必须由对方确认。</Text><View className="proposal-form surface"><Text className="form-label">约定名称</Text><Input className="form-input" maxlength={50} onInput={(event) => setTitle(event.detail.value)} placeholder="例如：争执时先暂停10分钟" value={title} /><Text className="form-label">具体怎么做</Text><Textarea autoHeight className="form-textarea" maxlength={300} onInput={(event) => setContent(event.detail.value)} placeholder="把双方都能接受的边界或做法写下来" value={content} /><Button className="primary-button proposal-submit" disabled={title.trim().length < 2 || content.trim().length < 2} onClick={submitProposal}>提交给对方共同确认</Button></View></View>
    <SafetyNotice />
    {mode === 'local-preview' ? <View className="preview-tools"><Text>本地体验视角：{state.viewerId === 'partner-a' ? '伴侣 A' : '伴侣 B'}</Text><Button className="soft-button" onClick={switchViewer}>切换视角测试</Button><Button className="preview-reset" onClick={reset}>重置本地体验数据</Button></View> : null}
    {mode === 'cloud' ? <View className="preview-tools"><Text>如你感到不安全或不想继续共享，可以立刻退出。</Text><Button className="preview-reset" onClick={leave}>退出共同空间</Button></View> : null}
    <Button className="soft-button" onClick={() => navigateTo({ url: '/pages/privacy/index' })}>数据与隐私设置</Button>
  </View></SpaceAccessGate>;
}
