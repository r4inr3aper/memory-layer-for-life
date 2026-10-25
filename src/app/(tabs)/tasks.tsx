/**
 * Tasks Tab Screen ('/(tabs)/tasks')
 *
 * Two lists:
 * - To do: the user's open items from their memories (TodoPanel), checked off, snoozed, or
 *   rescheduled here, in chat, or by Cooper.
 * - Schedules: each with its rule in its own timezone, its next run, and its latest result.
 *   A row opens the schedule's detail (history, edit, cancel, delete); the switch pauses or
 *   resumes it, and Run runs it now. "+ New" creates one from a form.
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Switch,
  ActivityIndicator,
  RefreshControl,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { Add01Icon, Target01Icon, Clock01Icon, PlayIcon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
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
  const [segment, setSegment] = useState<'todo' | 'schedules'>('todo');
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
      <View style={styles.segmentRow} accessibilityRole="tablist">
        {(
          [
            ['todo', 'To do'],
            ['schedules', 'Schedules'],
          ] as const
        ).map(([value, label]) => (
          <TouchableOpacity
            key={value}
            style={[styles.segment, segment === value && styles.segmentSelected]}
            onPress={() => setSegment(value)}
            activeOpacity={0.8}
            accessibilityRole="tab"
            accessibilityState={{ selected: segment === value }}>
            <Text style={[styles.segmentText, segment === value && styles.segmentTextSelected]}>
              {label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {segment === 'todo' ? <TodoPanel /> : null}

      <ScrollView
        style={[styles.scrollArea, segment !== 'schedules' && styles.hidden]}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={refreshTasks}
            tintColor={Colors.primary}
          />
        }>
        {/* Page Title & "+ New" Button */}
        <View style={styles.headerRow}>
          <Text style={styles.pageTitle}>Scheduled tasks</Text>
          <TouchableOpacity
            style={styles.newGoalBtn}
            onPress={() => setIsNewScheduleOpen(true)}
            activeOpacity={0.8}
            accessibilityRole="button"
            accessibilityLabel="New schedule">
            <HugeiconsIcon icon={Add01Icon} size={15} color={Colors.white} strokeWidth={2.4} />
            <Text style={styles.newGoalText}>New</Text>
          </TouchableOpacity>
        </View>

        {/* Task Rows */}
        {isLoading ? (
          <View style={styles.stateContainer}>
            <ActivityIndicator color={Colors.primary} />
            <Text style={styles.stateText}>Loading your schedules...</Text>
          </View>
        ) : tasks.length === 0 ? (
          <View style={styles.stateContainer}>
            <View style={styles.emptyIcon}>
              <HugeiconsIcon icon={Target01Icon} size={22} color={Colors.primary} />
            </View>
            <Text style={styles.emptyTitle}>No schedules yet</Text>
            <Text style={styles.emptyText}>
              Tap New, or confirm a schedule from chat, and it will appear here.
            </Text>
          </View>
        ) : (
          tasks.map((task, index) => {
            const isActive = task.status === 'active';
            const isCancelled = task.status === 'cancelled';
            const hasEnded = isCancelled || task.status === 'completed';
            const isUpdating = updatingTaskId === task.id;
            const isRunning = runningTaskId === task.id;

            return (
              <View key={task.id}>
                <TouchableOpacity
                  style={styles.taskRow}
                  onPress={() =>
                    router.push({ pathname: '/schedules/[id]', params: { id: task.id } })
                  }
                  activeOpacity={0.75}
                  accessibilityRole="button"
                  accessibilityHint="Opens the schedule's details and history">
                  {/* Left Target Icon Badge */}
                  <View
                    style={[
                      styles.iconContainer,
                      { backgroundColor: isActive ? Colors.primarySubtle : Colors.surfaceMuted },
                    ]}>
                    <HugeiconsIcon
                      icon={Target01Icon}
                      size={20}
                      color={isActive ? Colors.primary : Colors.textMuted}
                      strokeWidth={2}
                    />
                  </View>

                  {/* Center Content */}
                  <View style={styles.textContainer}>
                    <Text style={[styles.taskTitle, !isActive && styles.pausedText]}>
                      {task.title}
                    </Text>

                    <View style={styles.metaRow}>
                      <View style={styles.scheduleItem}>
                        <HugeiconsIcon icon={Clock01Icon} size={12} color={Colors.textMuted} />
                        <Text style={styles.taskSchedule}>
                          {formatScheduleRule(task)} · {formatTimezone(task.timezone)}
                        </Text>
                      </View>
                      <Text style={styles.metaDot}>•</Text>
                      <Text style={styles.executionsText}>
                        {task.run_count} {task.run_count === 1 ? 'run' : 'runs'}
                      </Text>
                      <Text style={styles.metaDot}>•</Text>
                      <Text style={styles.executionsText}>{STATUS_LABEL[task.status]}</Text>
                      {isActive && task.next_run_local ? (
                        <>
                          <Text style={styles.metaDot}>•</Text>
                          <Text style={styles.executionsText}>
                            Next {formatLocalDateTime(task.next_run_local)}
                          </Text>
                        </>
                      ) : null}
                      {task.last_run_at ? (
                        <>
                          <Text style={styles.metaDot}>•</Text>
                          <Text style={styles.executionsText}>
                            Last run {formatRelativeTime(task.last_run_at)}
                          </Text>
                        </>
                      ) : null}
                    </View>
                    {task.last_run_summary || task.last_run_error ? (
                      <View
                        style={[
                          styles.latestRunBox,
                          task.last_run_status !== 'succeeded' && styles.latestRunErrorBox,
                        ]}>
                        <Text
                          style={[
                            styles.latestRunLabel,
                            task.last_run_status !== 'succeeded' && styles.latestRunErrorLabel,
                          ]}>
                          {task.last_run_status === 'failed'
                            ? 'Last run failed'
                            : task.last_run_status === 'skipped'
                              ? 'Last run skipped'
                              : 'Last result'}
                        </Text>
                        <Text style={styles.latestRunText} numberOfLines={4}>
                          {task.last_run_status === 'succeeded'
                            ? task.last_run_summary
                            : task.last_run_error}
                        </Text>
                      </View>
                    ) : null}
                  </View>

                  {/* Right Controls: Switch & Run Button */}
                  <View style={styles.actionsCol}>
                    <Switch
                      value={isActive}
                      onValueChange={(value) => handleToggle(task, value)}
                      disabled={isUpdating || hasEnded}
                      trackColor={{ false: Colors.border, true: Colors.primaryLight }}
                      thumbColor={isActive ? Colors.primary : Colors.surfaceMuted}
                    />

                    <TouchableOpacity
                      style={[
                        styles.runManualBtn,
                        (isRunning || isCancelled) && styles.disabledAction,
                      ]}
                      onPress={() => confirmRunTask(task)}
                      disabled={runningTaskId !== null || isCancelled}
                      activeOpacity={0.75}>
                      {isRunning ? (
                        <ActivityIndicator size="small" color={Colors.primary} />
                      ) : (
                        <HugeiconsIcon
                          icon={PlayIcon}
                          size={12}
                          color={Colors.primary}
                          strokeWidth={2.4}
                        />
                      )}
                      <Text style={styles.runManualText}>{isRunning ? 'Running' : 'Run'}</Text>
                    </TouchableOpacity>
                  </View>
                </TouchableOpacity>

                {index < tasks.length - 1 && <View style={styles.divider} />}
              </View>
            );
          })
        )}
      </ScrollView>

      <ScheduleFormModal
        visible={isNewScheduleOpen}
        onClose={() => setIsNewScheduleOpen(false)}
        onSaved={handleScheduleCreated}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  segmentRow: {
    flexDirection: 'row',
    gap: 6,
    paddingHorizontal: 20,
    paddingTop: 8,
  },
  segment: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 18,
    backgroundColor: Colors.surface,
  },
  segmentSelected: {
    backgroundColor: Colors.iconDark,
  },
  segmentText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  segmentTextSelected: {
    color: Colors.white,
  },
  hidden: {
    display: 'none',
  },
  container: {
    flex: 1,
    backgroundColor: Colors.white,
  },
  scrollArea: {
    flex: 1,
  },
  scrollContent: {
    paddingBottom: 24,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    paddingTop: 12,
    paddingBottom: 16,
  },
  pageTitle: {
    fontSize: 28,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.5,
    flex: 1,
    paddingRight: 12,
  },
  newGoalBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.primary,
    paddingVertical: 7,
    paddingHorizontal: 12,
    borderRadius: 12,
    gap: 4,
  },
  newGoalText: {
    fontSize: 12,
    fontWeight: '700',
    color: Colors.white,
  },
  taskRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingVertical: 18,
    gap: 14,
  },
  iconContainer: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  textContainer: {
    flex: 1,
  },
  taskTitle: {
    fontSize: 15.5,
    fontWeight: '700',
    color: Colors.iconDark,
    lineHeight: 21,
    letterSpacing: -0.2,
  },
  pausedText: {
    color: Colors.textMuted,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 5,
  },
  scheduleItem: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  taskSchedule: {
    fontSize: 13,
    color: Colors.textSecondary,
    fontWeight: '500',
    letterSpacing: -0.1,
  },
  metaDot: {
    fontSize: 12,
    color: Colors.textMuted,
  },
  executionsText: {
    fontSize: 13,
    color: Colors.textSecondary,
    fontWeight: '500',
  },
  latestRunBox: {
    marginTop: 10,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: Colors.surface,
    borderWidth: 1,
    borderColor: Colors.borderLight,
  },
  latestRunErrorBox: {
    backgroundColor: Colors.errorLight,
    borderColor: Colors.error,
  },
  latestRunLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: Colors.textSecondary,
    marginBottom: 3,
  },
  latestRunErrorLabel: {
    color: Colors.error,
  },
  latestRunText: {
    fontSize: 12,
    lineHeight: 17,
    color: Colors.textPrimary,
    fontWeight: '500',
  },
  actionsCol: {
    alignItems: 'flex-end',
    gap: 8,
  },
  runManualBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.primarySubtle,
    borderWidth: 1,
    borderColor: Colors.primaryBorder,
    paddingVertical: 5,
    paddingHorizontal: 10,
    borderRadius: 8,
    gap: 4,
  },
  runManualText: {
    fontSize: 12,
    fontWeight: '700',
    color: Colors.primary,
  },
  disabledAction: {
    opacity: 0.7,
  },
  divider: {
    height: 1,
    backgroundColor: Colors.borderLight,
    marginHorizontal: 20,
  },
  stateContainer: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 36,
    paddingVertical: 72,
  },
  stateText: {
    marginTop: 12,
    fontSize: 14,
    color: Colors.textSecondary,
    fontWeight: '600',
  },
  emptyIcon: {
    width: 48,
    height: 48,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.primarySubtle,
    marginBottom: 14,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  emptyText: {
    marginTop: 6,
    fontSize: 14,
    lineHeight: 20,
    textAlign: 'center',
    color: Colors.textSecondary,
  },
});
