import { getStorageSync, setStorageSync } from '@tarojs/taro';
import { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import {
  confirmRule,
  createInitialRelationship,
  decideScoreAdjustment,
  NegativePoints,
  pendingForViewer,
  PositivePoints,
  proposeRule,
  proposeScoreAdjustment,
  RelationshipState,
  reviewCare,
  respondToRecord,
  submitCare,
  submitFeeling,
  switchViewer,
} from '../domain/relationship';
import { cloudRelationshipApi, CloudConnection, CloudProfile, initializeCloud, isCloudConfigured, loadCloudSnapshot, PrivacyNoticeStatus } from '../services/relationship-api';

const STORAGE_KEY = 'love-fueling-station-mini-v1';
type StorageMode = 'cloud' | 'local-preview';
type SyncStatus = 'loading' | 'ready' | 'error';
export type MutationOutcome = { saved: true; refreshed: boolean };
type RelationshipActions = {
  submitCare: (content: string, points: PositivePoints, uploadTicketId?: string, attachments?: Array<{ fileId: string }>) => Promise<MutationOutcome>;
  submitFeeling: (content: string, points: NegativePoints, uploadTicketId?: string, attachments?: Array<{ fileId: string }>) => Promise<MutationOutcome>;
  respond: (recordId: string, response: string) => Promise<MutationOutcome>;
  reviewCare: (recordId: string, decision: 'approved' | 'rejected', points: PositivePoints) => Promise<MutationOutcome>;
  proposeRule: (payload: { title: string; content: string }) => Promise<MutationOutcome>;
  confirmRule: (recordId: string, accept: boolean) => Promise<MutationOutcome>;
  proposeScoreAdjustment: (score: number, reason: string) => Promise<MutationOutcome>;
  decideScoreAdjustment: (recordId: string, accept: boolean) => Promise<MutationOutcome>;
  createInvite: (displayName: string, initialScore: number) => Promise<{ inviteCode: string; expiresAt: string }>;
  acceptInvite: (inviteCode: string, displayName: string, initialScore: number) => Promise<MutationOutcome>;
  acceptPrivacyNotice: () => Promise<MutationOutcome>;
  leaveSpace: () => Promise<MutationOutcome>;
  loadMoreRecords: () => Promise<void>;
  refresh: () => Promise<boolean>;
  switchViewer: () => void;
  reset: () => void;
};
type RelationshipContextValue = RelationshipActions & {
  state: RelationshipState;
  pending: ReturnType<typeof pendingForViewer>;
  mode: StorageMode;
  syncStatus: SyncStatus;
  syncError: string | null;
  profile: CloudProfile | null;
  connection: CloudConnection;
  privacyNotice: PrivacyNoticeStatus;
  hasMoreRecords: boolean;
  lastSyncedAt: string | null;
};

const RelationshipContext = createContext<RelationshipContextValue | null>(null);

function readStoredState(): RelationshipState {
  try {
    const stored = getStorageSync(STORAGE_KEY);
    if (stored && stored.schemaVersion === 2 && Array.isArray(stored.records)) return stored as RelationshipState;
  } catch {
    // 本地预览失败时回到无风险的演示初始状态。
  }
  return createInitialRelationship();
}

export function RelationshipProvider({ children }: PropsWithChildren) {
  const mode: StorageMode = isCloudConfigured() ? 'cloud' : 'local-preview';
  const [state, setState] = useState<RelationshipState>(readStoredState);
  const [syncStatus, setSyncStatus] = useState<SyncStatus>(mode === 'cloud' ? 'loading' : 'ready');
  const [syncError, setSyncError] = useState<string | null>(null);
  const [profile, setProfile] = useState<CloudProfile | null>(null);
  const [connection, setConnection] = useState<CloudConnection>({ status: 'unpaired' });
  const [privacyNotice, setPrivacyNotice] = useState<PrivacyNoticeStatus>({ version: '', required: false });
  const [hasMoreRecords, setHasMoreRecords] = useState(false);
  const [nextRecordCursor, setNextRecordCursor] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const refreshInFlight = useRef<Promise<boolean> | null>(null);

  const persistPreview = useCallback((next: RelationshipState) => {
    setState(next);
    setStorageSync(STORAGE_KEY, next);
  }, []);

  const refresh = useCallback(async () => {
    if (mode !== 'cloud') return true;
    if (refreshInFlight.current) return refreshInFlight.current;
    const task = (async () => {
      setSyncStatus('loading');
      setSyncError(null);
      try {
        initializeCloud();
        const snapshot = await loadCloudSnapshot();
        setState(snapshot.state);
        setProfile(snapshot.profile);
        setConnection(snapshot.connection);
        setPrivacyNotice(snapshot.privacyNotice);
        setHasMoreRecords(snapshot.hasMoreRecords);
        setNextRecordCursor(snapshot.nextRecordCursor);
        setLastSyncedAt(new Date().toISOString());
        setSyncStatus('ready');
        return true;
      } catch (error) {
        setSyncError(error instanceof Error ? error.message : '云端同步失败。');
        setSyncStatus('error');
        return false;
      } finally {
        refreshInFlight.current = null;
      }
    })();
    refreshInFlight.current = task;
    return task;
  }, [mode]);

  useEffect(() => {
    if (mode === 'cloud') void refresh();
  }, [mode, refresh]);

  const runCloudMutation = useCallback(async (operation: () => Promise<unknown>) => {
    await operation();
    const refreshed = await refresh();
    return { saved: true as const, refreshed };
  }, [refresh]);

  const actions = useMemo<RelationshipActions>(() => ({
    submitCare: async (content, points, uploadTicketId, attachments) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.submitCare(content, points, uploadTicketId, attachments));
      persistPreview(submitCare(state, content, points));
      return { saved: true, refreshed: true };
    },
    submitFeeling: async (content, points, uploadTicketId, attachments) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.submitFeeling(content, points, uploadTicketId, attachments));
      persistPreview(submitFeeling(state, content, points));
      return { saved: true, refreshed: true };
    },
    respond: async (recordId, response) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.respond(recordId, response));
      persistPreview(respondToRecord(state, recordId, response));
      return { saved: true, refreshed: true };
    },
    reviewCare: async (recordId, decision, points) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.reviewCare(recordId, decision, points));
      persistPreview(reviewCare(state, recordId, decision === 'approved', points));
      return { saved: true, refreshed: true };
    },
    proposeRule: async (payload) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.proposeRule(payload));
      persistPreview(proposeRule(state, payload));
      return { saved: true, refreshed: true };
    },
    confirmRule: async (recordId, accept) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.confirmRule(recordId, accept));
      persistPreview(confirmRule(state, recordId, accept));
      return { saved: true, refreshed: true };
    },
    proposeScoreAdjustment: async (score, reason) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.proposeScoreAdjustment(score, reason));
      persistPreview(proposeScoreAdjustment(state, score, reason));
      return { saved: true, refreshed: true };
    },
    decideScoreAdjustment: async (recordId, accept) => {
      if (mode === 'cloud') return runCloudMutation(() => cloudRelationshipApi.decideScoreAdjustment(recordId, accept));
      persistPreview(decideScoreAdjustment(state, recordId, accept));
      return { saved: true, refreshed: true };
    },
    createInvite: async (displayName, initialScore) => {
      if (mode !== 'cloud') throw new Error('请先配置 CloudBase，才能邀请另一位伴侣。');
      const invite = await cloudRelationshipApi.createInvite(displayName, initialScore);
      await refresh();
      return invite;
    },
    acceptInvite: async (inviteCode, displayName, initialScore) => {
      if (mode !== 'cloud') throw new Error('请先配置 CloudBase，才能接受邀请。');
      return runCloudMutation(() => cloudRelationshipApi.acceptInvite(inviteCode, displayName, initialScore));
    },
    acceptPrivacyNotice: async () => {
      if (mode !== 'cloud') throw new Error('本地预览模式不需要云端隐私同意。');
      return runCloudMutation(() => cloudRelationshipApi.acceptPrivacyNotice());
    },
    leaveSpace: async () => {
      if (mode !== 'cloud') throw new Error('本地预览模式没有共同空间可退出。');
      return runCloudMutation(() => cloudRelationshipApi.leaveSpace());
    },
    loadMoreRecords: async () => {
      if (mode !== 'cloud' || !hasMoreRecords) return;
      const page = await cloudRelationshipApi.listRecords(nextRecordCursor);
      setState((current) => ({ ...current, records: [...current.records, ...page.records] }));
      setHasMoreRecords(page.hasMore);
      setNextRecordCursor(page.nextCursor);
    },
    refresh,
    switchViewer: () => { if (mode === 'local-preview') persistPreview(switchViewer(state)); },
    reset: () => { if (mode === 'local-preview') persistPreview(createInitialRelationship()); },
  }), [hasMoreRecords, mode, nextRecordCursor, persistPreview, refresh, runCloudMutation, state]);

  const value = useMemo<RelationshipContextValue>(() => ({
    state, pending: pendingForViewer(state), mode, syncStatus, syncError, profile, connection, privacyNotice, hasMoreRecords, lastSyncedAt, ...actions,
  }), [actions, connection, hasMoreRecords, lastSyncedAt, mode, privacyNotice, profile, state, syncError, syncStatus]);
  return <RelationshipContext.Provider value={value}>{children}</RelationshipContext.Provider>;
}

export function useRelationship() {
  const context = useContext(RelationshipContext);
  if (!context) throw new Error('useRelationship 必须在 RelationshipProvider 内使用。');
  return context;
}
