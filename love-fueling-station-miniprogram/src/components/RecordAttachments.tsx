import { Image, View } from '@tarojs/components';
import { useEffect, useState } from 'react';
import { resolveCloudFileUrl } from '../services/relationship-api';

export function RecordAttachments({ attachments }: { attachments?: Array<{ fileId: string }> }) {
  const [urls, setUrls] = useState<string[]>([]);
  useEffect(() => {
    let active = true;
    if (!attachments?.length) { setUrls([]); return () => { active = false; }; }
    void Promise.all(attachments.map((item) => resolveCloudFileUrl(item.fileId).catch(() => null))).then((resolved) => {
      if (active) setUrls(resolved.filter((value): value is string => Boolean(value)));
    });
    return () => { active = false; };
  }, [attachments]);
  if (!urls.length) return null;
  return <View className="record-attachments">{urls.map((url) => <Image key={url} src={url} mode="aspectFill" />)}</View>;
}
