import { chooseImage, showToast, switchTab } from '@tarojs/taro';
import { Button, Image, Text, Textarea, View } from '@tarojs/components';
import { useState } from 'react';
import { NegativePoints, PositivePoints } from '../../domain/relationship';
import { useRelationship } from '../../store/relationship-store';
import { SpaceAccessGate } from '../../components/SpaceAccessGate';
import { usePageCloudRefresh } from '../../components/CloudSyncBridge';
import { maxRecordAttachments, recordMediaUploadsEnabled } from '../../config/media';
import { uploadRecordAttachments } from '../../services/relationship-api';
import './index.scss';

type RecordMode = 'care' | 'feeling';

export default function RecordPage() {
  const { mode: storageMode, submitCare, submitFeeling } = useRelationship();
  usePageCloudRefresh();
  const [mode, setMode] = useState<RecordMode>('care');
  const [content, setContent] = useState('');
  const [carePoints, setCarePoints] = useState<PositivePoints>(3);
  const [feelingPoints, setFeelingPoints] = useState<NegativePoints>(-3);
  const [submitting, setSubmitting] = useState(false);
  const [localPhotoPaths, setLocalPhotoPaths] = useState<string[]>([]);
  const trimmed = content.trim();

  async function submit() {
    if (trimmed.length < 2 || submitting) return;
    setSubmitting(true);
    try {
      const uploaded = localPhotoPaths.length > 0 ? await uploadRecordAttachments(localPhotoPaths) : { uploadTicketId: undefined, attachments: [] };
      const outcome = mode === 'care'
        ? await submitCare(trimmed, carePoints, uploaded.uploadTicketId, uploaded.attachments)
        : await submitFeeling(trimmed, feelingPoints, uploaded.uploadTicketId, uploaded.attachments);
      setContent('');
      setLocalPhotoPaths([]);
      showToast({ title: outcome.refreshed ? (mode === 'care' ? '已提交，等待对方审批' : `感受已记录，已扣${Math.abs(feelingPoints)}分`) : '已保存到云端，页面暂未刷新', icon: 'none' });
      switchTab({ url: '/pages/home/index' });
    } catch (error) {
      showToast({ title: error instanceof Error ? error.message : '暂时无法保存', icon: 'none' });
    } finally {
      setSubmitting(false);
    }
  }

  async function choosePhotos() {
    if (submitting) return;
    try {
      const selected = await chooseImage({ count: maxRecordAttachments - localPhotoPaths.length, sizeType: ['compressed'], sourceType: ['album', 'camera'] });
      setLocalPhotoPaths((current) => [...current, ...selected.tempFilePaths].slice(0, maxRecordAttachments));
    } catch (error) {
      if (!/cancel/i.test(error instanceof Error ? error.message : '')) showToast({ title: '暂时无法选择照片', icon: 'none' });
    }
  }

  return <SpaceAccessGate><View className="page-shell record-page">
      <Text className="page-title">记录一件事</Text>
      <Text className="page-subtitle">可以是一份被看见的行动，也可以是一份需要被认真回应的感受。</Text>

      <View className="record-mode surface">
        <Button className={mode === 'care' ? 'mode-option is-active' : 'mode-option'} onClick={() => setMode('care')}>
          <Text>✦</Text><Text>记录行动</Text><Text className="mode-description">让对方看见你的用心</Text>
        </Button>
        <Button className={mode === 'feeling' ? 'mode-option is-active' : 'mode-option'} onClick={() => setMode('feeling')}>
          <Text>◌</Text><Text>记录感受</Text><Text className="mode-description">邀请对方认真回应</Text>
        </Button>
      </View>

      <View className="record-form">
        <Text className="input-label">{mode === 'care' ? '你想让对方看见什么？' : '发生了什么？你希望对方先听见什么？'}</Text>
        <View className="textarea-shell surface">
          <Textarea
            autoHeight
            maxlength={300}
            onInput={(event) => setContent(event.detail.value)}
            placeholder={mode === 'care' ? '例如：今天提前准备好晚饭，也问了问你今天累不累。' : '例如：刚才我感到被忽略了，我希望我们先把彼此的想法听完。'}
            value={content}
          />
          <Text className="character-count">{content.length}/300</Text>
        </View>
        <View className="points-picker surface">
          <Text className="input-label">{mode === 'care' ? '建议对方审批时加多少分？' : '这份感受需要直接扣多少分？'}</Text>
          <View className="points-options">
            {(mode === 'care' ? [1, 3, 5] : [-1, -3, -5]).map((points) => {
              const active = mode === 'care' ? carePoints === points : feelingPoints === points;
              return <Button className={active ? 'points-option is-active' : 'points-option'} key={points} onClick={() => mode === 'care' ? setCarePoints(points as PositivePoints) : setFeelingPoints(points as NegativePoints)}>{points > 0 ? `+${points}` : points} 分</Button>;
            })}
          </View>
        </View>
        <Text className="record-hint">{mode === 'care' ? '对方可以通过、调整为+1/+3/+5，或驳回；提交时不直接加分。' : '感受会立即扣分，但仍邀请对方认真回应；请只记录具体事件与感受。'}</Text>
        {storageMode === 'cloud' && recordMediaUploadsEnabled ? <View className="photo-section surface"><Text className="input-label">添加照片（可选）</Text><Text className="photo-hint">最多三张，仅作为记录补充；请勿上传证件、儿童或他人的私密照片。</Text><View className="photo-grid">{localPhotoPaths.map((path) => <View className="photo-item" key={path}><Image src={path} mode="aspectFill" /><Button className="photo-remove" onClick={() => setLocalPhotoPaths((current) => current.filter((item) => item !== path))}>移除</Button></View>)}{localPhotoPaths.length < maxRecordAttachments ? <Button className="photo-add" onClick={choosePhotos}>添加照片</Button> : null}</View></View> : null}
      </View>

      <Button className="primary-button record-submit" disabled={trimmed.length < 2 || submitting} onClick={submit}>{submitting ? '正在保存…' : mode === 'care' ? '提交给对方审批' : `记录并扣${Math.abs(feelingPoints)}分`}</Button>
    </View></SpaceAccessGate>;
}
