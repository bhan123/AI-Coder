import { stopPullDownRefresh, useDidShow, usePullDownRefresh } from '@tarojs/taro';
import { PropsWithChildren, useEffect, useRef } from 'react';
import { useRelationship } from '../store/relationship-store';

/**
 * 云端数据不做高频轮询：回到前台和用户主动下拉时同步一次即可。
 * store 内部会合并同时发生的刷新，避免 tab 切换和 onShow 造成瀑布请求。
 */
export function CloudSyncBridge({ children }: PropsWithChildren) {
  const { mode, refresh } = useRelationship();
  const mounted = useRef(false);

  useDidShow(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    if (mode === 'cloud') void refresh();
  });

  useEffect(() => {
    mounted.current = true;
  }, []);

  return <>{children}</>;
}

/** 在启用了 enablePullDownRefresh 的页面中调用，给用户一条明确的手动同步路径。 */
export function usePageCloudRefresh() {
  const { mode, refresh } = useRelationship();
  usePullDownRefresh(() => {
    if (mode !== 'cloud') {
      stopPullDownRefresh();
      return;
    }
    void refresh().finally(() => stopPullDownRefresh());
  });
}
