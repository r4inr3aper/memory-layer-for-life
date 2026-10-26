/**
 * Schedule Detail Screen ('/schedules/[id]')
 *
 * One schedule: when it runs (in its own timezone), where results go, the task it runs,
 * and every run, including slots that were skipped and why. From here the user runs it
 * now, pauses or resumes it, edits it (Edit in the bar), cancels it, or deletes it with
 * its history. The schedule's title is the large title; the run history is one inset group
 * drawn by the list's rows, so it can page in as the user scrolls.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Pressable, RefreshControl, StyleSheet, View } from 'react-native';
import Animated from 'react-native-reanimated';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  AppText,
  Button,
  EmptyState,
  LargeTitle,
  ListRow,
  ListSection,
  PressableScale,
  ScreenHeader,
  useScrollY,
} from '@/components/ui';
import { ScheduleFormModal } from '@/components/tasks/ScheduleFormModal';
import { Colors } from '@/constants/colors';
import { Hairline, Radius, ScreenMargin, continuous } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { useRequireSession } from '@/hooks/useRequireSession';
import { ApiError, getErrorMessage, isAbortError } from '@/lib/api/client';
import {
  deleteSchedule,
  getSchedule,
  listScheduleRuns,
  startScheduleRun,
  updateScheduleStatus,
  waitForScheduleRun,
} from '@/lib/api/schedules';
import { ensureMainThread } from '@/lib/api/threads';
import type { Schedule, ScheduleRun, ScheduleStatus } from '@/lib/api/types';
import { confirmAsync } from '@/lib/dialogs';
import { formatLocalDateTime, formatScheduleRule, formatTimezone } from '@/lib/formatSchedule';
import { formatRelativeTime } from '@/lib/formatTime';
import { openChatThread } from '@/lib/navigation';
import { DELIVERY_OPTIONS } from '@/lib/scheduleForm';

const RUNS_PAGE_LIMIT = 20;

type Action = 'run' | 'toggle' | 'cancel' | 'delete';

const STATUS_LABEL: Record<ScheduleStatus, string> = {
  active: 'Active',
  paused: 'Paused',
  cancelled: 'Cancelled',
  completed: 'Completed',
};

const RUN_STATUS: Record<ScheduleRun['status'], { label: string; color: string }> = {
  running: { label: 'Running', color: Colors.tint },
  succeeded: { label: 'Done', color: Colors.systemGreen },
  failed: { label: 'Failed', color: Colors.systemRed },
  skipped: { label: 'Skipped', color: Colors.systemOrange },
};

export default function ScheduleDetailScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { scrollY, onScroll } = useScrollY();
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading');
  const [errorMessage, setErrorMessage] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [busy, setBusy] = useState<Action | null>(null);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
  // Cancels run polling when the screen goes away.
  const pollRef = useRef<AbortController | null>(null);

  useEffect(() => () => pollRef.current?.abort(), []);

  const load = useCallback(
    (signal?: AbortSignal) => {
      if (!id) return Promise.resolve();
      return Promise.all([
        getSchedule(id, signal),
        listScheduleRuns(id, { limit: RUNS_PAGE_LIMIT, offset: 0 }, signal),
      ])
        .then(([loaded, page]) => {
          setSchedule(loaded);
          setRuns(page.items);
          setRunsTotal(page.total);
          setStatus('ready');
        })
        .catch((error) => {
          if (isAbortError(error, signal)) return;
          if (error instanceof ApiError && error.status === 404) {
            setStatus('missing');
            return;
          }
          console.error('Failed to load the schedule:', error);
          setErrorMessage(getErrorMessage(error, 'Could not load this schedule'));
          setStatus((current) => (current === 'ready' ? current : 'error'));
        });
    },
    [id]
  );

  // Reload whenever the screen is shown, so runs that finished meanwhile appear.
  useFocusEffect(
    useCallback(() => {
      if (!hasSession) return undefined;
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [hasSession, load])
  );

  const handleRefresh = () => {
    setIsRefreshing(true);
    void load().finally(() => setIsRefreshing(false));
  };

  const handleLoadMore = () => {
    if (!id || isLoadingMore || runs.length >= runsTotal) return;
    setIsLoadingMore(true);
    listScheduleRuns(id, { limit: RUNS_PAGE_LIMIT, offset: runs.length })
      .then((page) => {
        setRuns((current) => {
          const seen = new Set(current.map((run) => run.id));
          return [...current, ...page.items.filter((run) => !seen.has(run.id))];
        });
        setRunsTotal(page.total);
      })
      .catch((error) => showToast(getErrorMessage(error, 'Could not load more runs')))
      .finally(() => setIsLoadingMore(false));
  };

  const act = async (action: Action, work: () => Promise<void>) => {
    if (busy) return;
    setBusy(action);
    try {
      await work();
    } catch (error) {
      if (isAbortError(error, pollRef.current?.signal)) return;
      console.error(`Schedule ${action} failed:`, error);
      showToast(getErrorMessage(error, 'Something went wrong'), 3500);
    } finally {
      setBusy(null);
    }
  };

  const handleRunNow = () =>
    act('run', async () => {
      if (!schedule) return;
      const confirmed = await confirmAsync({
        title: 'Run now?',
        message: `${schedule.title} will run once now. Its next scheduled run doesn't change.`,
        confirmText: 'Run now',
      });
      if (!confirmed) return;
      const started = await startScheduleRun(schedule.id);
      showToast('Running…');
      await load();
      pollRef.current?.abort();
      const controller = new AbortController();
      pollRef.current = controller;
      const finished = await waitForScheduleRun(schedule.id, started, {
        signal: controller.signal,
      });
      await load();
      if (finished.status === 'succeeded') showToast('Run finished');
      else if (finished.status === 'failed') {
        showToast(finished.error_message ?? 'The run failed', 3500);
      } else showToast('Still running. Pull to refresh later.');
    });

  const handleTogglePause = () =>
    act('toggle', async () => {
      if (!schedule) return;
      const next: ScheduleStatus = schedule.status === 'active' ? 'paused' : 'active';
      setSchedule(await updateScheduleStatus(schedule.id, next));
      showToast(next === 'paused' ? 'Paused' : 'Resumed');
    });

  const handleCancel = () =>
    act('cancel', async () => {
      if (!schedule) return;
      const confirmed = await confirmAsync({
        title: 'Cancel this schedule?',
        message: 'It will never run again. You can still see its history, or delete it.',
        confirmText: 'Cancel schedule',
        destructive: true,
      });
      if (!confirmed) return;
      setSchedule(await updateScheduleStatus(schedule.id, 'cancelled'));
      showToast('Schedule cancelled');
    });

  const handleDelete = () =>
    act('delete', async () => {
      if (!schedule) return;
      const confirmed = await confirmAsync({
        title: 'Delete this schedule?',
        message:
          'The schedule and its run history will be deleted. Results already posted stay in ' +
          "your chat. This can't be undone.",
        confirmText: 'Delete',
        destructive: true,
      });
      if (!confirmed) return;
      await deleteSchedule(schedule.id);
      showToast('Schedule deleted');
      if (router.canGoBack()) router.back();
      else router.replace('/(tabs)/tasks');
    });

  const openRunInChat = async () => {
    try {
      const threadId = schedule?.source_thread_id ?? (await ensureMainThread()).id;
      openChatThread(threadId);
    } catch (error) {
      showToast(getErrorMessage(error, 'Could not open the chat'));
    }
  };

  if (!hasSession) {
    return <View style={styles.safeArea} />;
  }

  const isReady = status === 'ready' && schedule !== null;
  const canEdit = isReady && schedule.status !== 'cancelled';

  const header = schedule ? (
    <ScheduleSummary
      schedule={schedule}
      busy={busy}
      onRunNow={handleRunNow}
      onTogglePause={handleTogglePause}
      onCancel={handleCancel}
      onDelete={handleDelete}
      onOpenSource={
        schedule.source_thread_id ? () => openChatThread(schedule.source_thread_id!) : null
      }
      runsTotal={runsTotal}
    />
  ) : null;

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right', 'bottom']}>
      <ScreenHeader
        title={isReady ? schedule.title : 'Schedule'}
        fallbackHref="/(tabs)/tasks"
        scrollY={isReady ? scrollY : undefined}
        right={
          canEdit ? (
            <PressableScale
              onPress={() => setIsEditOpen(true)}
              disabled={busy !== null}
              accessibilityRole="button"
              style={styles.editButton}>
              <AppText variant="body" color="tint">
                Edit
              </AppText>
            </PressableScale>
          ) : undefined
        }
      />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.secondaryLabel} />
      ) : status === 'missing' ? (
        <EmptyState
          title="This schedule no longer exists"
          message="It may have been deleted."
          style={styles.centered}
        />
      ) : status === 'error' ? (
        <EmptyState
          title={errorMessage}
          actionTitle="Try again"
          onAction={() => {
            setStatus('loading');
            void load();
          }}
          style={styles.centered}
        />
      ) : (
        <Animated.FlatList
          data={runs}
          keyExtractor={(run) => run.id}
          onScroll={onScroll}
          scrollEventThrottle={16}
          ListHeaderComponent={header ?? undefined}
          contentContainerStyle={styles.listContent}
          renderItem={({ item, index }) => (
            <RunRow
              run={item}
              isFirst={index === 0}
              isLast={index === runs.length - 1}
              isExpanded={expandedRunId === item.id}
              onToggle={() => setExpandedRunId((current) => (current === item.id ? null : item.id))}
              onOpenInChat={item.chat_message_id ? openRunInChat : null}
            />
          )}
          ItemSeparatorComponent={RunSeparator}
          ListEmptyComponent={
            <View style={[styles.runCell, styles.runFirst, styles.runLast, styles.noRuns]}>
              <AppText variant="subheadline" color="secondary">
                No runs yet. Run it now to try it out.
              </AppText>
            </View>
          }
          ListFooterComponent={
            isLoadingMore ? (
              <ActivityIndicator style={styles.spinner} color={Colors.secondaryLabel} />
            ) : undefined
          }
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.4}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
              tintColor={Colors.secondaryLabel}
              colors={[Colors.tint]}
            />
          }
        />
      )}

      <ScheduleFormModal
        visible={isEditOpen}
        schedule={schedule}
        onClose={() => setIsEditOpen(false)}
        onSaved={(saved) => {
          setSchedule(saved);
          void load();
        }}
      />
    </SafeAreaView>
  );
}

function ScheduleSummary({
  schedule,
  busy,
  runsTotal,
  onRunNow,
  onTogglePause,
  onCancel,
  onDelete,
  onOpenSource,
}: {
  schedule: Schedule;
  busy: Action | null;
  runsTotal: number;
  onRunNow: () => void;
  onTogglePause: () => void;
  onCancel: () => void;
  onDelete: () => void;
  onOpenSource: (() => void) | null;
}) {
  const isCancelled = schedule.status === 'cancelled';
  const canPause = schedule.status === 'active' || schedule.status === 'paused';
  const delivery =
    DELIVERY_OPTIONS.find((option) => option.value === schedule.delivery)?.label ?? 'Chat';
  const nextRun = schedule.next_run_local
    ? `${formatLocalDateTime(schedule.next_run_local)} (${formatTimezone(schedule.timezone)})`
    : schedule.status === 'completed'
      ? 'None: it has run'
      : schedule.status === 'cancelled'
        ? 'None: cancelled'
        : 'When resumed';
  // Another action in flight blocks this one; its own row keeps a spinner instead.
  const blocked = (action: Action) => busy !== null && busy !== action;
  const spinner = (action: Action) =>
    busy === action ? <ActivityIndicator size="small" color={Colors.secondaryLabel} /> : undefined;

  return (
    <View>
      <LargeTitle title={schedule.title} subtitle={STATUS_LABEL[schedule.status]} />

      <ListSection>
        <DetailRow label="When" value={formatScheduleRule(schedule)} />
        <DetailRow
          label="Timezone"
          value={`${formatTimezone(schedule.timezone)} (${schedule.timezone})`}
        />
        <DetailRow
          label="Next run"
          value={canPause && schedule.status === 'paused' ? 'Paused' : nextRun}
        />
        <DetailRow
          label="Results go to"
          value={schedule.delivery_target ? `${delivery} · ${schedule.delivery_target}` : delivery}
        />
      </ListSection>

      <ListSection header="Task">
        <View style={styles.taskCell}>
          <AppText variant="body">{schedule.task}</AppText>
        </View>
        {onOpenSource ? <ListRow title="Open the chat it came from" onPress={onOpenSource} /> : null}
      </ListSection>

      <ListSection>
        <ListRow
          title="Run now"
          action
          accessory={spinner('run')}
          disabled={isCancelled || blocked('run')}
          onPress={onRunNow}
        />
        {canPause ? (
          <ListRow
            title={schedule.status === 'active' ? 'Pause' : 'Resume'}
            action
            accessory={spinner('toggle')}
            disabled={blocked('toggle')}
            onPress={onTogglePause}
          />
        ) : null}
      </ListSection>

      <ListSection>
        {canPause ? (
          <ListRow
            title="Cancel schedule"
            destructive
            action
            accessory={spinner('cancel')}
            disabled={blocked('cancel')}
            onPress={onCancel}
          />
        ) : null}
        <ListRow
          title="Delete schedule"
          destructive
          action
          accessory={spinner('delete')}
          disabled={blocked('delete')}
          onPress={onDelete}
        />
      </ListSection>

      <AppText variant="footnote" color="secondary" style={styles.historyHeader}>
        {`History${runsTotal ? ` · ${runsTotal}` : ''}`.toUpperCase()}
      </AppText>
    </View>
  );
}

/** A label over its value, as iOS shows details that can run long. */
function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailCell}>
      <AppText variant="footnote" color="secondary">
        {label}
      </AppText>
      <AppText variant="body">{value}</AppText>
    </View>
  );
}

function RunRow({
  run,
  isFirst,
  isLast,
  isExpanded,
  onToggle,
  onOpenInChat,
}: {
  run: ScheduleRun;
  /** The history is one inset group: its first and last rows round its corners. */
  isFirst: boolean;
  isLast: boolean;
  isExpanded: boolean;
  onToggle: () => void;
  onOpenInChat: (() => void) | null;
}) {
  const [pressed, setPressed] = useState(false);
  const state = RUN_STATUS[run.status];
  const text = run.status === 'succeeded' ? run.summary : run.error_message;
  return (
    <Animated.View
      style={[
        styles.runCell,
        isFirst && styles.runFirst,
        isLast && styles.runLast,
        pressed ? styles.cellPressed : styles.cellIdle,
      ]}>
      <Pressable
        style={styles.runMain}
        onPress={onToggle}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        disabled={!text}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button"
        accessibilityState={{ expanded: isExpanded }}>
        <View style={styles.runHeader}>
          <View style={[styles.runDot, { backgroundColor: state.color }]} />
          <AppText variant="headline">{state.label}</AppText>
          <AppText variant="footnote" color="secondary" numberOfLines={1} style={styles.runMeta}>
            {run.trigger === 'manual' ? 'Run manually' : 'Scheduled'} ·{' '}
            {formatRelativeTime(run.scheduled_for ?? run.started_at)}
          </AppText>
        </View>
        {text ? (
          <AppText variant="subheadline" numberOfLines={isExpanded ? undefined : 3}>
            {text}
          </AppText>
        ) : null}
      </Pressable>
      {onOpenInChat && run.status !== 'skipped' ? (
        <Button
          title="Open in chat"
          variant="plain"
          size="small"
          onPress={onOpenInChat}
          containerStyle={styles.openInChat}
        />
      ) : null}
    </Animated.View>
  );
}

/** The hairline between runs, inset from the group's leading edge like ListSection's. */
function RunSeparator() {
  return (
    <View style={styles.separatorTrack}>
      <View style={styles.separator} />
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  spinner: {
    marginVertical: 24,
  },
  centered: {
    flex: 1,
  },
  editButton: {
    paddingHorizontal: 4,
    paddingVertical: 10,
  },
  listContent: {
    paddingBottom: 32,
  },
  detailCell: {
    paddingHorizontal: 16,
    paddingVertical: 10,
    gap: 2,
  },
  taskCell: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  historyHeader: {
    paddingHorizontal: ScreenMargin + 16,
    marginBottom: 7,
    letterSpacing: 0.2,
  },
  runCell: {
    marginHorizontal: ScreenMargin,
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  runFirst: {
    ...continuous,
    borderTopLeftRadius: Radius.md,
    borderTopRightRadius: Radius.md,
  },
  runLast: {
    ...continuous,
    borderBottomLeftRadius: Radius.md,
    borderBottomRightRadius: Radius.md,
  },
  // Highlight at once on touch down; fade out after release, as ListRow does.
  cellPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  cellIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  runMain: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 4,
  },
  runHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  runDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  runMeta: {
    flex: 1,
  },
  openInChat: {
    alignSelf: 'flex-start',
    marginLeft: 12,
    marginTop: -6,
    marginBottom: 6,
  },
  noRuns: {
    paddingHorizontal: 16,
    paddingVertical: 14,
  },
  separatorTrack: {
    marginHorizontal: ScreenMargin,
    backgroundColor: Colors.secondaryGroupedBackground,
  },
  separator: {
    height: Hairline,
    marginLeft: 16,
    backgroundColor: Colors.separator,
  },
});
