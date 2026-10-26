/**
 * Tasks Tab Screen ('/(tabs)/tasks')
 *
 * A large title with New, a segmented control, and one of two inset-grouped lists:
 * - To do: the user's open items from their memories (TodoPanel), checked off, snoozed, or
 *   rescheduled here, in chat, or by Cooper.
 * - Schedules: each with its rule in its own timezone, its next run, and its latest result.
 *   A row opens the schedule's detail (history, edit, cancel, delete); the switch pauses or
 *   resumes it, and Run runs it now. New creates one from a form.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import Animated from 'react-native-reanimated';
import { useFocusEffect, useRouter } from 'expo-router';
import { Add01Icon, Clock01Icon, PlayIcon, Target01Icon } from '@hugeicons/core-free-icons';
import {
  AppSwitch,
  AppText,
  Button,
  EmptyState,
  IconTile,
  ListSection,
  SegmentedControl,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { ScreenMargin } from '@/constants/theme';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import {
  listSchedules,
  startScheduleRun,
  updateScheduleStatus,
  waitForScheduleRun,
} from '@/lib/api/schedules';
import type { Schedule, ScheduleStatus } from '@/lib/api/types';
import { formatLocalDateTime, formatScheduleRule, formatTimezone } from '@/lib/formatSchedule';
import { formatRelativeTime } from '@/lib/formatTime';
import { showToast } from '@/context/ToastContext';
import { confirmAsync } from '@/lib/dialogs';
import { ScheduleFormModal } from '@/components/tasks/ScheduleFormModal';
import { TodoPanel } from '@/components/tasks/TodoPanel';

const SCHEDULE_PAGE_LIMIT = 100;

type Segment = 'todo' | 'schedules';

const SEGMENTS = [
  { value: 'todo', label: 'To do' },
  { value: 'schedules', label: 'Schedules' },
] as const satisfies readonly { value: Segment; label: string }[];

const STATUS_LABEL: Record<ScheduleStatus, string> = {
  active: 'Active',
  paused: 'Paused',
  cancelled: 'Cancelled',
  completed: 'Completed',
};

export default function TasksScreen() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Schedule[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [updatingTaskId, setUpdatingTaskId] = useState<string | null>(null);
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);
  const [isNewScheduleOpen, setIsNewScheduleOpen] = useState(false);
  const [isNewTodoOpen, setIsNewTodoOpen] = useState(false);
  const [segment, setSegment] = useState<Segment>('todo');
  // Cancels run polling when the screen goes away.
  const runAbortRef = useRef<AbortController | null>(null);

  useEffect(() => () => runAbortRef.current?.abort(), []);

  /** Fetches the schedules into the list; failures show a toast. */
  const fetchTasks = useCallback((signal?: AbortSignal) => {
    return listSchedules({ limit: SCHEDULE_PAGE_LIMIT }, signal)
      .then((page) => setTasks(page.items))
      .catch((error) => {
        if (isAbortError(error, signal)) return;
        console.error('Failed to load scheduled tasks:', error);
        showToast(getErrorMessage(error, 'Could not load your schedules'));
      });
  }, []);

  // Tabs stay mounted, so reload whenever Tasks is opened: a schedule confirmed in chat,
  // or a run that finished meanwhile, shows up without a pull. `isLoading` starts out true
  // and only covers the first load.
  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void fetchTasks(controller.signal).finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
      return () => controller.abort();
    }, [fetchTasks])
  );

  const refreshTasks = async () => {
    setIsRefreshing(true);
    await fetchTasks();
    setIsRefreshing(false);
  };

  const handleScheduleCreated = (schedule: Schedule) => {
    setTasks((prev) => [schedule, ...prev.filter((task) => task.id !== schedule.id)]);
  };

  const handleToggle = async (task: Schedule, nextIsActive: boolean) => {
    setUpdatingTaskId(task.id);
    const previousTasks = tasks;
    const nextStatus: ScheduleStatus = nextIsActive ? 'active' : 'paused';

    setTasks((prev) =>
      prev.map((item) => (item.id === task.id ? { ...item, status: nextStatus } : item))
    );

    try {
      const updatedTask = await updateScheduleStatus(task.id, nextStatus);
      setTasks((prev) => prev.map((item) => (item.id === task.id ? updatedTask : item)));
      showToast(`${task.title} is now ${nextIsActive ? 'active' : 'paused'}`);
    } catch (error) {
      console.error('Failed to update scheduled task status:', error);
      setTasks(previousTasks);
      showToast(getErrorMessage(error, 'Could not update the schedule'));
    } finally {
      setUpdatingTaskId(null);
    }
  };

  const confirmRunTask = async (task: Schedule) => {
    const confirmed = await confirmAsync({
      title: 'Run now?',
      message: `Run "${task.title}" immediately?`,
      confirmText: 'Run',
    });
    if (confirmed) {
      void runTaskNow(task);
    }
  };

  /** Starts a run in the background, then polls it until it finishes. */
  const runTaskNow = async (task: Schedule) => {
    runAbortRef.current?.abort();
    const controller = new AbortController();
    runAbortRef.current = controller;
    setRunningTaskId(task.id);

    try {
      const started = await startScheduleRun(task.id);
      const run = await waitForScheduleRun(task.id, started, { signal: controller.signal });

      if (run.status === 'succeeded') {
        showToast(`${task.title} ran successfully`);
      } else if (run.status === 'failed') {
        showToast(run.error_message || `${task.title} failed`);
      } else {
        showToast(`${task.title} is still running. Pull to refresh later.`);
      }
      await refreshTasks();
    } catch (error) {
      if (isAbortError(error, controller.signal)) return;
      console.error('Failed to run scheduled task:', error);
      showToast(getErrorMessage(error, 'Could not run scheduled goal'));
    } finally {
      if (runAbortRef.current === controller) {
        runAbortRef.current = null;
        setRunningTaskId(null);
      }
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.top}>
        <View style={styles.titleRow}>
          <AppText variant="largeTitle" numberOfLines={1} style={styles.title}>
            Tasks
          </AppText>
          <Button
            title="New"
            icon={Add01Icon}
            variant="tinted"
            size="small"
            onPress={() =>
              segment === 'todo' ? setIsNewTodoOpen(true) : setIsNewScheduleOpen(true)
            }
            accessibilityLabel={segment === 'todo' ? 'New to-do' : 'New schedule'}
          />
        </View>
        <SegmentedControl
          segments={SEGMENTS}
          value={segment}
          onChange={setSegment}
          style={styles.segments}
        />
      </View>

      {/* One list at a time. Hiding the other with `display: 'none'` is not enough: on
          Android a ScrollView with a RefreshControl sits in a wrapper that keeps its
          flex, so the hidden Schedules list took half the screen from To do. */}
      {segment === 'todo' ? (
        <TodoPanel isAdding={isNewTodoOpen} onAddingChange={setIsNewTodoOpen} />
      ) : (
        <ScrollView
          style={styles.scrollArea}
          contentContainerStyle={styles.scrollContent}
          showsVerticalScrollIndicator={false}
          refreshControl={
            <RefreshControl
              refreshing={isRefreshing}
              onRefresh={refreshTasks}
              tintColor={Colors.secondaryLabel}
              colors={[Colors.tint]}
            />
          }>
          {isLoading ? (
            <View style={styles.loading}>
              <ActivityIndicator color={Colors.secondaryLabel} />
              <AppText variant="footnote" color="secondary">
                Loading your schedules...
              </AppText>
            </View>
          ) : tasks.length === 0 ? (
            <EmptyState
              icon={Target01Icon}
              title="No schedules yet"
              message="Tap New, or confirm a schedule from chat, and it will appear here."
            />
          ) : (
            <ListSection>
              {tasks.map((task) => (
                <ScheduleRow
                  key={task.id}
                  leading
                  task={task}
                  isUpdating={updatingTaskId === task.id}
                  isRunning={runningTaskId === task.id}
                  runLocked={runningTaskId !== null}
                  onOpen={() =>
                    router.push({ pathname: '/schedules/[id]', params: { id: task.id } })
                  }
                  onToggle={(value) => handleToggle(task, value)}
                  onRun={() => confirmRunTask(task)}
                />
              ))}
            </ListSection>
          )}
        </ScrollView>
      )}

      <ScheduleFormModal
        visible={isNewScheduleOpen}
        onClose={() => setIsNewScheduleOpen(false)}
        onSaved={handleScheduleCreated}
      />
    </View>
  );
}

/**
 * One schedule in the list: its rule, its next run (or why there is none), and how its
 * latest run went. The texts open the detail; the switch and Run act in place.
 */
function ScheduleRow({
  task,
  isUpdating,
  isRunning,
  runLocked,
  onOpen,
  onToggle,
  onRun,
}: {
  task: Schedule;
  isUpdating: boolean;
  isRunning: boolean;
  /** A run of some schedule is in flight; only one runs at a time. */
  runLocked: boolean;
  onOpen: () => void;
  onToggle: (isActive: boolean) => void;
  onRun: () => void;
  /** Read by ListSection: insets the separator below this row past its icon. */
  leading?: boolean;
}) {
  const [pressed, setPressed] = useState(false);
  const isActive = task.status === 'active';
  const isCancelled = task.status === 'cancelled';
  const hasEnded = isCancelled || task.status === 'completed';

  const runs = `${task.run_count} ${task.run_count === 1 ? 'run' : 'runs'}`;
  const nextLine =
    isActive && task.next_run_local
      ? `Next ${formatLocalDateTime(task.next_run_local)} · ${runs}`
      : `${STATUS_LABEL[task.status]} · ${runs}`;

  const resultText =
    task.last_run_status === 'succeeded' ? task.last_run_summary : task.last_run_error;
  const hasResult = Boolean(task.last_run_summary || task.last_run_error);
  const resultFailed = task.last_run_status !== 'succeeded';
  const resultLabel =
    task.last_run_status === 'failed'
      ? 'Last run failed'
      : task.last_run_status === 'skipped'
        ? 'Last run skipped'
        : 'Last result';
  const resultTone =
    task.last_run_status === 'failed'
      ? Colors.systemRed
      : task.last_run_status === 'skipped'
        ? Colors.systemOrange
        : Colors.systemGreen;

  return (
    <Animated.View style={[styles.row, pressed ? styles.rowPressed : styles.rowIdle]}>
      <Pressable
        style={styles.rowMain}
        onPress={onOpen}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button"
        accessibilityHint="Opens the schedule's details and history">
        <IconTile icon={Clock01Icon} color={isActive ? Colors.tint : Colors.systemGray} />
        <View style={styles.rowTexts}>
          <AppText variant="headline" color={isActive ? 'primary' : 'secondary'}>
            {task.title}
          </AppText>
          <AppText variant="subheadline" color="secondary">
            {formatScheduleRule(task)} · {formatTimezone(task.timezone)}
          </AppText>
          <AppText variant="footnote" color="secondary">
            {nextLine}
          </AppText>
          {hasResult ? (
            <View style={styles.result}>
              <View style={styles.resultHeader}>
                <View style={[styles.resultDot, { backgroundColor: resultTone }]} />
                <AppText
                  variant="footnote"
                  weight="600"
                  color={resultFailed ? resultTone : 'secondary'}
                  numberOfLines={1}
                  style={styles.resultLabel}>
                  {resultLabel}
                  {task.last_run_at ? (
                    <AppText variant="footnote" color="secondary">
                      {` · ${formatRelativeTime(task.last_run_at)}`}
                    </AppText>
                  ) : null}
                </AppText>
              </View>
              {resultText ? (
                <AppText variant="footnote" numberOfLines={3}>
                  {resultText}
                </AppText>
              ) : null}
            </View>
          ) : null}
        </View>
      </Pressable>

      <View style={styles.rowControls}>
        <AppSwitch
          value={isActive}
          onValueChange={onToggle}
          disabled={isUpdating || hasEnded}
          accessibilityLabel={`${task.title} active`}
        />
        <Button
          title="Run"
          icon={PlayIcon}
          variant="tinted"
          size="small"
          loading={isRunning}
          disabled={(runLocked && !isRunning) || isCancelled}
          onPress={onRun}
        />
      </View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.groupedBackground,
  },
  top: {
    paddingHorizontal: ScreenMargin,
    paddingBottom: 8,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingTop: 4,
    paddingBottom: 10,
    paddingLeft: 4,
  },
  title: {
    flex: 1,
  },
  // The track's default fill is drawn for white surfaces; on the grouped gray it needs the
  // stronger fill to read as a control.
  segments: {
    backgroundColor: Colors.fill,
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingTop: 8,
    paddingBottom: 32,
  },
  loading: {
    alignItems: 'center',
    gap: 12,
    paddingVertical: 72,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
    paddingLeft: 16,
    paddingRight: 14,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  // Highlight at once on touch down; fade out after release, as ListRow does.
  rowPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  rowIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  rowMain: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 14,
    paddingVertical: 12,
  },
  rowTexts: {
    flex: 1,
    gap: 2,
  },
  result: {
    marginTop: 6,
    gap: 2,
  },
  resultHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  resultDot: {
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  resultLabel: {
    flexShrink: 1,
  },
  rowControls: {
    alignItems: 'flex-end',
    gap: 10,
    paddingVertical: 12,
  },
});
