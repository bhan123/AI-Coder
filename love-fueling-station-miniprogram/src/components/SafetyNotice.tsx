import { Text, View } from '@tarojs/components';

export function SafetyNotice() {
  return (
    <View className="safety-card">
      <Text className="safety-icon">◎</Text>
      <View className="safety-copy">
        <Text className="safety-title">先把安全放在前面</Text>
        <Text className="safety-text">出现严重控制、威胁或暴力时，不适合由这个工具调解。请优先离开危险场景、联系可信的人或当地紧急与专业支持。</Text>
      </View>
    </View>
  );
}
