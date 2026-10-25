/**
 * Schedule Detail Screen ('/schedules/[id]')
 *
 * One schedule: when it runs (in its own timezone), where results go, the task it runs,
 * and every run, including slots that were skipped and why. From here the user runs it
 * now, pauses or resumes it, edits it, cancels it, or deletes it with its history.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useFocusEffect, useLocalSearchParams, useRouter } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { ScreenHeader } from '@/components/common/ScreenHeader';
import { ScheduleFormModal } from '@/components/tasks/ScheduleFormModal';
import { Colors } from '@/constants/colors';
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
  running: { label: 'Running', color: Colors.primary },
  succeeded: { label: 'Done', color: Colors.success },
  failed: { label: 'Failed', color: Colors.error },
  skipped: { label: 'Skipped', color: Colors.warning },
};

export default function ScheduleDetailScreen() {
  const hasSession = useRequireSession();
  const router = useRouter();
  const { id } = useLocalSearchParams<{ id: string }>();
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

  const header = schedule ? (
    <ScheduleSummary
      schedule={schedule}
      busy={busy}
      onRunNow={handleRunNow}
      onTogglePause={handleTogglePause}
      onEdit={() => setIsEditOpen(true)}
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
      <ScreenHeader title="Schedule" fallbackHref="/(tabs)/tasks" />

      {status === 'loading' ? (
        <ActivityIndicator style={styles.spinner} color={Colors.primary} />
      ) : status === 'missing' ? (
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>This schedule no longer exists</Text>
          <Text style={styles.emptyText}>It may have been deleted.</Text>
        </View>
      ) : status === 'error' ? (
        <View style={styles.centered}>
          <Text style={styles.emptyTitle}>{errorMessage}</Text>
          <TouchableOpacity
            style={styles.retryButton}
            onPress={() => {
              setStatus('loading');
              void load();
            }}
            activeOpacity={0.75}>
            <Text style={styles.retryText}>Try again</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={runs}
          keyExtractor={(run) => run.id}
          ListHeaderComponent={header ?? undefined}
          contentContainerStyle={styles.listContent}
          renderItem={({ item }) => (
            <RunRow
              run={item}
              isExpanded={expandedRunId === item.id}
              onToggle={() => setExpandedRunId((current) => (current === item.id ? null : item.id))}
              onOpenInChat={item.chat_message_id ? openRunInChat : null}
            />
          )}
          ListEmptyComponent={
            <Text style={styles.noRunsText}>No runs yet. Run it now to try it out.</Text>
          }
          ListFooterComponent={
            isLoadingMore ? (
              <ActivityIndicator style={styles.spinner} color={Colors.primary} />
            ) : undefined
          }
          onEndReached={handleLoadMore}
          onEndReachedThreshold={0.4}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={handleRefresh}
              tintColor={Colors.primary}
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
  onEdit,
  onCancel,
  onDelete,
  onOpenSource,
}: {
  schedule: Schedule;
  busy: Action | null;
  runsTotal: number;
  onRunNow: () => void;
  onTogglePause: () => void;
  onEdit: () => void;
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

  return (
    <View>
      <View style={styles.card}>
        <View style={styles.titleRow}>
          <Text style={styles.title}>{schedule.title}</Text>
          <View style={[styles.statusPill, styles[`status_${schedule.status}`]]}>
            <Text style={styles.statusText}>{STATUS_LABEL[schedule.status]}</Text>
          </View>
        </View>

        <Detail label="When" value={formatScheduleRule(schedule)} />
        <Detail
          label="Timezone"
          value={`${formatTimezone(schedule.timezone)} (${schedule.timezone})`}
        />
        <Detail
          label="Next run"
          value={canPause && schedule.status === 'paused' ? 'Paused' : nextRun}
        />
        <Detail
          label="Results go to"
          value={schedule.delivery_target ? `${delivery} · ${schedule.delivery_target}` : delivery}
        />
        <Text style={styles.detailLabel}>Task</Text>
        <Text style={styles.taskText}>{schedule.task}</Text>
        {onOpenSource ? (
          <TouchableOpacity onPress={onOpenSource} activeOpacity={0.7}>
            <Text style={styles.linkText}>Open the chat it came from</Text>
          </TouchableOpacity>
        ) : null}

        <View style={styles.actionRow}>
          <ActionButton
            label="Run now"
            primary
            busy={busy === 'run'}
            disabled={isCancelled || busy !== null}
            onPress={onRunNow}
          />
          {canPause ? (
            <ActionButton
              label={schedule.status === 'active' ? 'Pause' : 'Resume'}
              busy={busy === 'toggle'}
              disabled={busy !== null}
              onPress={onTogglePause}
            />
          ) : null}
          {!isCancelled ? (
            <ActionButton label="Edit" disabled={busy !== null} onPress={onEdit} />
          ) : null}
        </View>
        <View style={styles.actionRow}>
          {schedule.status === 'active' || schedule.status === 'paused' ? (
            <ActionButton
              label="Cancel schedule"
              danger
              busy={busy === 'cancel'}
              disabled={busy !== null}
              onPress={onCancel}
            />
          ) : null}
          <ActionButton
            label="Delete"
            danger
            busy={busy === 'delete'}
            disabled={busy !== null}
            onPress={onDelete}
          />
        </View>
      </View>

      <Text style={styles.sectionTitle}>History{runsTotal ? ` · ${runsTotal}` : ''}</Text>
    </View>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

function ActionButton({
  label,
  onPress,
  primary = false,
  danger = false,
  busy = false,
  disabled = false,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
  danger?: boolean;
  busy?: boolean;
  disabled?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[
        styles.actionButton,
        primary && styles.actionPrimary,
        danger && styles.actionDanger,
        disabled && !busy && styles.actionDisabled,
      ]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.8}
      accessibilityRole="button"
      accessibilityState={{ disabled, busy }}>
      {busy ? (
        <ActivityIndicator size="small" color={primary ? Colors.white : Colors.iconDark} />
      ) : (
        <Text
          style={[
            styles.actionText,
            primary && styles.actionTextPrimary,
            danger && styles.actionTextDanger,
          ]}>
          {label}
        </Text>
      )}
    </TouchableOpacity>
  );
}

function RunRow({
  run,
  isExpanded,
  onToggle,
  onOpenInChat,
}: {
  run: ScheduleRun;
  isExpanded: boolean;
  onToggle: () => void;
  onOpenInChat: (() => void) | null;
}) {
  const state = RUN_STATUS[run.status];
  const text = run.status === 'succeeded' ? run.summary : run.error_message;
  return (
    <TouchableOpacity
      style={styles.runRow}
      onPress={onToggle}
      activeOpacity={0.8}
      disabled={!text}
      accessibilityRole="button"
      accessibilityState={{ expanded: isExpanded }}>
      <View style={styles.runHeader}>
        <View style={[styles.runDot, { backgroundColor: state.color }]} />
        <Text style={styles.runStatus}>{state.label}</Text>
        <Text style={styles.runMeta}>
          {run.trigger === 'manual' ? 'Run manually' : 'Scheduled'} ·{' '}
          {formatRelativeTime(run.scheduled_for ?? run.started_at)}
        </Text>
      </View>
      {text ? (
        <Text style={styles.runText} numberOfLines={isExpanded ? undefined : 3}>
          {text}
        </Text>
      ) : null}
      {onOpenInChat && run.status !== 'skipped' ? (
        <TouchableOpacity onPress={onOpenInChat} activeOpacity={0.7}>
          <Text style={styles.linkText}>Open in chat</Text>
        </TouchableOpacity>
      ) : null}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  spinner: {
    marginVertical: 24,
  },
  centered: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  emptyTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
    textAlign: 'center',
  },
  emptyText: {
    marginTop: 6,
    fontSize: 13,
    color: Colors.textSecondary,
    textAlign: 'center',
  },
  retryButton: {
    marginTop: 14,
    paddingHorizontal: 18,
    paddingVertical: 9,
    borderRadius: 18,
    backgroundColor: Colors.primarySubtle,
  },
  retryText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  listContent: {
    padding: 16,
    paddingBottom: 32,
  },
  card: {
    padding: 16,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 10,
    marginBottom: 8,
  },
  title: {
    flex: 1,
    fontSize: 18,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.3,
  },
  statusPill: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 10,
  },
  status_active: {
    backgroundColor: Colors.successLight,
  },
  status_paused: {
    backgroundColor: Colors.warningLight,
  },
  status_cancelled: {
    backgroundColor: Colors.errorLight,
  },
  status_completed: {
    backgroundColor: Colors.surface,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  detailRow: {
    marginTop: 10,
  },
  detailLabel: {
    marginTop: 10,
    fontSize: 11,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  detailValue: {
    marginTop: 2,
    fontSize: 14.5,
    color: Colors.iconDark,
  },
  taskText: {
    marginTop: 2,
    fontSize: 14.5,
    lineHeight: 20,
    color: Colors.iconDark,
  },
  linkText: {
    marginTop: 8,
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 14,
  },
  actionButton: {
    minWidth: 84,
    height: 38,
    paddingHorizontal: 14,
    borderRadius: 19,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  actionPrimary: {
    backgroundColor: Colors.primary,
  },
  actionDanger: {
    backgroundColor: Colors.errorLight,
  },
  actionDisabled: {
    opacity: 0.45,
  },
  actionText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  actionTextPrimary: {
    color: Colors.white,
  },
  actionTextDanger: {
    color: Colors.error,
  },
  sectionTitle: {
    marginTop: 22,
    marginBottom: 8,
    fontSize: 12,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  noRunsText: {
    fontSize: 13.5,
    color: Colors.textSecondary,
  },
  runRow: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
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
  runStatus: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  runMeta: {
    flex: 1,
    fontSize: 12.5,
    color: Colors.textSecondary,
  },
  runText: {
    marginTop: 6,
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.iconDark,
  },
});
