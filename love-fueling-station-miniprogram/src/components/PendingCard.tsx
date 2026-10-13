import { Button, Text, View } from '@tarojs/components';
import { RelationshipRecord, partnerName } from '../domain/relationship';

type PendingCardProps = {
  record: RelationshipRecord;
  viewerId: 'partner-a' | 'partner-b';
  onRespond: (record: RelationshipRecord) => void;
};

export function PendingCard({ record, viewerId, onRespond }: PendingCardProps) {
  const isRule = record.kind === 'rule';
  const title = isRule ? '一条共同约定等待确认' : record.kind === 'feeling' ? '一份感受等待回应' : '一件行动希望被看见';
  const content = isRule ? record.title : record.content;
  return (
    <View className="pending-card surface">
      <View className="pending-card-header"><Text>{title}</Text><Text>{partnerName(record.authorId, viewerId)}记录</Text></View>
      <Text className="pending-card-content">{content}</Text>
      <Button className="primary-button pending-card-button" onClick={() => onRespond(record)}>{isRule ? '查看并共同确认' : '认真回应'}</Button>
    </View>
  );
}
