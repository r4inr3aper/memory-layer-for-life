/**
 * TodoPanel Component
 *
 * The user's to-do list on the Tasks tab, from their life state: overdue, today, this
 * week, later, no date, goals, and pending reminders, with what got done this week. The
 * circle checks an item off; "⋯" snoozes it, moves its due date, or stops tracking it; a
 * row opens the memory behind it. "+ New" adds a to-do. Reloads whenever the tab is shown.
 */

import React, { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Modal,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  Add01Icon,
  AlarmClockIcon,
  CheckmarkCircle02Icon,
  CircleIcon,
  MoreHorizontalIcon,
} from '@hugeicons/core-free-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { closeItem, getLife, scheduleItem } from '@/lib/api/life';
import type { LifeOverview, MemoryItem } from '@/lib/api/types';
import { dueChoices, dueLabel, reminderLabel, snoozeChoices } from '@/lib/life';
import { TodoEditorModal } from './TodoEditorModal';

const SECTIONS = [
  ['overdue', 'Overdue'],
  ['due_today', 'Today'],
  ['upcoming', 'This week'],
  ['later', 'Later'],
  ['someday', 'No date'],
  ['goals', 'Goals'],
] as const;

export function TodoPanel() {
  const router = useRouter();
  const [life, setLife] = useState<LifeOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [isAdding, setIsAdding] = useState(false);
  const [actionsFor, setActionsFor] = useState<MemoryItem | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    return getLife(signal)
      .then((overview) => {
        setLife(overview);
        setError(null);
      })
      .catch((loadError) => {
        if (isAbortError(loadError, signal)) return;
        setError(getErrorMessage(loadError, "Couldn't load your list"));
      });
  }, []);

  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [load])
  );

  const act = async (item: MemoryItem, work: () => Promise<unknown>, message: string) => {
    if (busyId) return;
    setBusyId(item.id);
    try {
      await work();
      showToast(message);
      await load();
    } catch (actionError) {
      showToast(getErrorMessage(actionError, 'Something went wrong'), 3500);
    } finally {
      setBusyId(null);
    }
  };

  const openItem = (item: MemoryItem) =>
    router.push({ pathname: '/memories/[id]', params: { id: item.id } });

  const stale = new Set(life?.stale_ids ?? []);
  const isEmpty =
    life !== null &&
    SECTIONS.every(([key]) => life[key].length === 0) &&
    life.reminders.length === 0;

  return (
    <View style={styles.container}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
        refreshControl={
          <RefreshControl
            refreshing={isRefreshing}
            onRefresh={() => {
              setIsRefreshing(true);
              void load().finally(() => setIsRefreshing(false));
            }}
            tintColor={Colors.primary}
          />
        }>
        <View style={styles.headerRow}>
          <Text style={styles.pageTitle}>To do</Text>
          <TouchableOpacity
            style={styles.newButton}
            onPress={() => setIsAdding(true)}
            activeOpacity={0.8}
            accessibilityRole="button"
            accessibilityLabel="New to-do">
            <HugeiconsIcon icon={Add01Icon} size={15} color={Colors.white} strokeWidth={2.4} />
            <Text style={styles.newText}>New</Text>
          </TouchableOpacity>
        </View>

        {error ? (
          <TouchableOpacity style={styles.errorBox} onPress={() => void load()}>
            <Text style={styles.errorText}>{error}</Text>
            <Text style={styles.link}>Try again</Text>
          </TouchableOpacity>
        ) : null}

        {life === null && !error ? <ActivityIndicator style={styles.spinner} /> : null}

        {isEmpty ? (
          <Text style={styles.emptyText}>
            Nothing open. Tell Cooper what you need to do, like &quot;remind me to call Mum at
            6&quot;, or tap New.
          </Text>
        ) : null}

        {life
          ? SECTIONS.map(([key, title]) =>
              life[key].length ? (
                <View key={key}>
                  <Text style={[styles.sectionTitle, key === 'overdue' && styles.overdueTitle]}>
                    {title} · {life[key].length}
                  </Text>
                  {life[key].map((item) => (
                    <TodoRow
                      key={item.id}
                      item={item}
                      today={life.today}
                      stale={stale.has(item.id)}
                      busy={busyId === item.id}
                      onToggle={() => act(item, () => closeItem(item.id, 'complete'), 'Done')}
                      onOpen={() => openItem(item)}
                      onMore={() => setActionsFor(item)}
                    />
                  ))}
                </View>
              ) : null
            )
          : null}

        {life?.reminders.length ? (
          <View>
            <Text style={styles.sectionTitle}>Reminders · {life.reminders.length}</Text>
            {life.reminders.map((item) => (
              <TouchableOpacity
                key={item.id}
                style={styles.reminderRow}
                onPress={() => openItem(item)}
                activeOpacity={0.7}>
                <HugeiconsIcon icon={AlarmClockIcon} size={16} color={Colors.primary} />
                <Text style={styles.reminderText} numberOfLines={1}>
                  {item.content}
                </Text>
                <Text style={styles.meta}>
                  {item.remind_at ? reminderLabel(item.remind_at) : ''}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        ) : null}

        {life?.recently_done.length ? (
          <View>
            <Text style={styles.sectionTitle}>Done this week · {life.recently_done.length}</Text>
            {life.recently_done.slice(0, 10).map((item) => (
              <View key={item.id} style={styles.doneRow}>
                <HugeiconsIcon icon={CheckmarkCircle02Icon} size={20} color={Colors.success} />
                <Text style={styles.doneText} numberOfLines={1}>
                  {item.content}
                </Text>
                <TouchableOpacity
                  onPress={() => act(item, () => closeItem(item.id, 'reopen'), 'Open again')}
                  disabled={busyId !== null}>
                  <Text style={styles.link}>Undo</Text>
                </TouchableOpacity>
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>

      <TodoEditorModal
        visible={isAdding}
        onClose={() => setIsAdding(false)}
        onSaved={() => {
          setIsAdding(false);
          showToast('Added');
          void load();
        }}
      />

      <TodoActionsSheet
        item={actionsFor}
        today={life?.today ?? ''}
        onClose={() => setActionsFor(null)}
        onChoose={(work, message) => {
          const item = actionsFor;
          setActionsFor(null);
          if (item) void act(item, () => work(item), message);
        }}
        onOpen={() => {
          const item = actionsFor;
          setActionsFor(null);
          if (item) openItem(item);
        }}
      />
    </View>
  );
}

function TodoRow({
  item,
  today,
  stale,
  busy,
  onToggle,
  onOpen,
  onMore,
}: {
  item: MemoryItem;
  today: string;
  stale: boolean;
  busy: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onMore: () => void;
}) {
  const overdue = item.due_on !== null && item.due_on < today;
  const meta: string[] = [];
  if (item.due_on) meta.push(dueLabel(item.due_on, today));
  if (item.remind_at) meta.push(`Reminder ${reminderLabel(item.remind_at)}`);
  if (stale) meta.push('Gone quiet');

  return (
    <View style={styles.row}>
      <TouchableOpacity
        onPress={onToggle}
        disabled={busy}
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        accessibilityRole="checkbox"
        accessibilityState={{ checked: false, busy }}
        accessibilityLabel={`Mark ${item.content} done`}>
        {busy ? (
          <ActivityIndicator size="small" color={Colors.primary} />
        ) : (
          <HugeiconsIcon icon={CircleIcon} size={22} color={Colors.iconMuted} />
        )}
      </TouchableOpacity>
      <TouchableOpacity style={styles.rowBody} onPress={onOpen} activeOpacity={0.7}>
        <Text style={styles.rowText}>{item.content}</Text>
        {meta.length ? (
          <Text style={[styles.meta, overdue && styles.overdueMeta]}>{meta.join(' · ')}</Text>
        ) : null}
      </TouchableOpacity>
      <TouchableOpacity
        onPress={onMore}
        hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
        accessibilityRole="button"
        accessibilityLabel="More actions">
        <HugeiconsIcon icon={MoreHorizontalIcon} size={20} color={Colors.iconMuted} />
      </TouchableOpacity>
    </View>
  );
}

function TodoActionsSheet({
  item,
  today,
  onClose,
  onChoose,
  onOpen,
}: {
  item: MemoryItem | null;
  today: string;
  onClose: () => void;
  onChoose: (work: (item: MemoryItem) => Promise<unknown>, message: string) => void;
  onOpen: () => void;
}) {
  const insets = useSafeAreaInsets();
  if (!item) return null;
  const snoozes = snoozeChoices();
  const dues = today ? dueChoices(today) : [];
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <TouchableWithoutFeedback onPress={onClose}>
          <View style={styles.backdrop} />
        </TouchableWithoutFeedback>
        <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]}>
          <Text style={styles.sheetTitle} numberOfLines={2}>
            {item.content}
          </Text>
          <Text style={styles.sheetLabel}>Remind me</Text>
          <View style={styles.chipRow}>
            {snoozes.map((choice) => (
              <SheetChip
                key={choice.label}
                label={choice.label}
                onPress={() =>
                  onChoose(
                    (target) => scheduleItem(target.id, { remind_at: choice.value }),
                    `Reminder ${reminderLabel(choice.value)}`
                  )
                }
              />
            ))}
          </View>
          <Text style={styles.sheetLabel}>Due</Text>
          <View style={styles.chipRow}>
            {dues.map((choice) => (
              <SheetChip
                key={choice.label}
                label={choice.label}
                onPress={() =>
                  onChoose(
                    (target) => scheduleItem(target.id, { due_on: choice.value }),
                    `Due ${choice.label.toLowerCase()}`
                  )
                }
              />
            ))}
            {item.due_on ? (
              <SheetChip
                label="No date"
                onPress={() =>
                  onChoose((target) => scheduleItem(target.id, { due_on: null }), 'No due date')
                }
              />
            ) : null}
          </View>
          <View style={styles.sheetActions}>
            <TouchableOpacity style={styles.sheetButton} onPress={onOpen}>
              <Text style={styles.sheetButtonText}>Open</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[styles.sheetButton, styles.dropButton]}
              onPress={() =>
                onChoose((target) => closeItem(target.id, 'drop'), 'No longer tracked')
              }>
              <Text style={[styles.sheetButtonText, styles.dropText]}>Stop tracking</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
}

function SheetChip({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <TouchableOpacity
      style={styles.chip}
      onPress={onPress}
      activeOpacity={0.75}
      accessibilityRole="button">
      <Text style={styles.chipText}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    paddingHorizontal: 20,
    paddingBottom: 140,
  },
  headerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 12,
    marginBottom: 4,
  },
  pageTitle: {
    fontSize: 26,
    fontWeight: '800',
    color: Colors.iconDark,
    letterSpacing: -0.6,
  },
  newButton: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 14,
    height: 34,
    borderRadius: 17,
    backgroundColor: Colors.primary,
  },
  newText: {
    fontSize: 13.5,
    fontWeight: '700',
    color: Colors.white,
  },
  spinner: {
    marginVertical: 24,
  },
  emptyText: {
    marginTop: 16,
    fontSize: 14,
    lineHeight: 20,
    color: Colors.textSecondary,
  },
  errorBox: {
    marginTop: 12,
    padding: 14,
    borderRadius: 14,
    backgroundColor: Colors.errorLight,
    gap: 6,
  },
  errorText: {
    fontSize: 13.5,
    color: Colors.error,
  },
  link: {
    fontSize: 13,
    fontWeight: '700',
    color: Colors.primary,
  },
  sectionTitle: {
    marginTop: 20,
    marginBottom: 4,
    fontSize: 12,
    fontWeight: '700',
    color: Colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  overdueTitle: {
    color: Colors.error,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingVertical: 11,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  rowBody: {
    flex: 1,
  },
  rowText: {
    fontSize: 15,
    lineHeight: 21,
    color: Colors.textPrimary,
  },
  meta: {
    marginTop: 2,
    fontSize: 12.5,
    color: Colors.textSecondary,
  },
  overdueMeta: {
    color: Colors.error,
  },
  reminderRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  reminderText: {
    flex: 1,
    fontSize: 14.5,
    color: Colors.textPrimary,
  },
  doneRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    paddingVertical: 9,
  },
  doneText: {
    flex: 1,
    fontSize: 14.5,
    color: Colors.textSecondary,
    textDecorationLine: 'line-through',
  },
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: Colors.overlay,
  },
  sheet: {
    backgroundColor: Colors.white,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingTop: 18,
    paddingHorizontal: 20,
  },
  sheetTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: Colors.iconDark,
  },
  sheetLabel: {
    marginTop: 16,
    marginBottom: 6,
    fontSize: 11,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: Colors.border,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  sheetActions: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 20,
  },
  sheetButton: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sheetButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  dropButton: {
    backgroundColor: Colors.errorLight,
  },
  dropText: {
    color: Colors.error,
  },
});

export default TodoPanel;
