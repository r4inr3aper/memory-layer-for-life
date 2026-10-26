/**
 * TodoPanel Component
 *
 * The user's to-do list on the Tasks tab, from their life state, most actionable first, in
 * inset-grouped sections as in Reminders:
 * - Now: overdue, today, and this week, with today's reminders. Always open.
 * - From your import: items of an imported chat nobody has looked at, asked about once
 *   (Keep / Done / Drop) instead of filling the list with an old export's tasks.
 * - Goals; open questions (nothing to tick off); the backlog (later and undated), folded
 *   away until asked for; and what got done this week.
 * The circle checks an item off: it fills with the tint at once, and the row leaves when the
 * list reloads. "⋯" snoozes it, moves its due date, or stops tracking it; a row opens the
 * memory behind it. The Tasks screen's New button opens the editor (`isAdding`). Reloads
 * whenever the tab is shown.
 */

import React, { useCallback, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from 'react-native';
import Animated, { useReducedMotion } from 'react-native-reanimated';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  AlarmClockIcon,
  CheckmarkCircle02Icon,
  MoreHorizontalIcon,
  Tick02Icon,
} from '@hugeicons/core-free-icons';
import {
  AppText,
  BottomSheet,
  Button,
  EmptyState,
  IconButton,
  ListRow,
  ListSection,
  PressableScale,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Motion, ScreenMargin } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { closeItem, getLife, scheduleItem } from '@/lib/api/life';
import { changeMemoryStatus } from '@/lib/api/memories';
import type { LifeOverview, MemoryItem } from '@/lib/api/types';
import { haptic } from '@/lib/haptics';
import { dueChoices, dueLabel, reminderLabel, snoozeChoices } from '@/lib/life';
import { TodoEditorModal } from './TodoEditorModal';

// What "Now" shows: everything with a date in the coming week.
const NOW_SECTIONS = [
  ['overdue', 'Overdue'],
  ['due_today', 'Today'],
  ['upcoming', 'This week'],
] as const;

type Folded = 'triage' | 'questions' | 'backlog';

export interface TodoPanelProps {
  /** Whether the new to-do sheet is open (the Tasks screen's New button opens it). */
  isAdding: boolean;
  onAddingChange: (isAdding: boolean) => void;
}

export function TodoPanel({ isAdding, onAddingChange }: TodoPanelProps) {
  const router = useRouter();
  const [life, setLife] = useState<LifeOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionsFor, setActionsFor] = useState<MemoryItem | null>(null);
  const [open, setOpen] = useState<ReadonlySet<Folded>>(new Set());

  const toggle = (section: Folded) =>
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      return next;
    });

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
  const nowCount = life ? NOW_SECTIONS.reduce((sum, [key]) => sum + life[key].length, 0) : 0;
  const backlog = life ? [...life.later, ...life.someday] : [];
  const isEmpty =
    life !== null &&
    nowCount === 0 &&
    backlog.length === 0 &&
    life.goals.length === 0 &&
    life.questions.length === 0 &&
    life.triage.length === 0 &&
    life.reminders.length === 0;

  const row = (item: MemoryItem) => (
    <TodoRow
      key={item.id}
      leading
      item={item}
      today={life?.today ?? ''}
      stale={stale.has(item.id)}
      busy={busyId === item.id}
      locked={busyId !== null}
      onToggle={() => act(item, () => closeItem(item.id, 'complete'), 'Done')}
      onOpen={() => openItem(item)}
      onMore={() => setActionsFor(item)}
    />
  );

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
            tintColor={Colors.secondaryLabel}
            colors={[Colors.tint]}
          />
        }>
        {error ? (
          <ListSection>
            <ListRow title={error} numberOfLines={3} />
            <ListRow title="Try again" action onPress={() => void load()} />
          </ListSection>
        ) : null}

        {life === null && !error ? (
          <ActivityIndicator style={styles.spinner} color={Colors.secondaryLabel} />
        ) : null}

        {isEmpty ? (
          <EmptyState
            icon={CheckmarkCircle02Icon}
            title="Nothing open"
            message="Tell Cooper what you need to do, like “remind me to call Mum at 6”, or tap New."
          />
        ) : null}

        {life && !isEmpty ? (
          <>
            {nowCount === 0 ? (
              <AppText variant="subheadline" color="secondary" style={styles.note}>
                Nothing due this week.
              </AppText>
            ) : (
              NOW_SECTIONS.map(([key, title]) =>
                life[key].length ? (
                  <ListSection key={key} header={`${title} · ${life[key].length}`}>
                    {life[key].map(row)}
                  </ListSection>
                ) : null
              )
            )}

            {life.reminders.length ? (
              <ListSection header={`Reminders · ${life.reminders.length}`}>
                {life.reminders.map((item) => (
                  <ListRow
                    key={item.id}
                    icon={AlarmClockIcon}
                    iconColor={Colors.systemOrange}
                    title={item.title || item.content}
                    value={item.remind_at ? reminderLabel(item.remind_at) : undefined}
                    onPress={() => openItem(item)}
                  />
                ))}
              </ListSection>
            ) : null}

            {life.triage.length ? (
              <FoldSection
                title="From your imported chat"
                count={life.triage.length}
                hint="Still relevant? Keep what is, tick off or drop the rest."
                open={open.has('triage')}
                onToggle={() => toggle('triage')}>
                {life.triage.map((item) => (
                  <TriageRow
                    key={item.id}
                    item={item}
                    busy={busyId === item.id}
                    onOpen={() => openItem(item)}
                    onKeep={() =>
                      act(item, () => changeMemoryStatus(item.id, 'accept'), 'Kept on your list')
                    }
                    onDone={() => act(item, () => closeItem(item.id, 'complete'), 'Done')}
                    onDrop={() => act(item, () => closeItem(item.id, 'drop'), 'No longer tracked')}
                  />
                ))}
              </FoldSection>
            ) : null}

            {life.goals.length ? (
              <ListSection header={`Goals · ${life.goals.length}`}>
                {life.goals.map(row)}
              </ListSection>
            ) : null}

            {life.questions.length ? (
              <FoldSection
                title="Open questions"
                count={life.questions.length}
                open={open.has('questions')}
                onToggle={() => toggle('questions')}>
                {life.questions.map(row)}
              </FoldSection>
            ) : null}

            {backlog.length ? (
              <FoldSection
                title="Backlog"
                count={backlog.length}
                hint="Later, or no date yet."
                open={open.has('backlog')}
                onToggle={() => toggle('backlog')}>
                {backlog.map(row)}
              </FoldSection>
            ) : null}
          </>
        ) : null}

        {life?.recently_done.length ? (
          <ListSection header={`Done this week · ${life.recently_done.length}`}>
            {life.recently_done.slice(0, 10).map((item) => (
              <DoneRow
                key={item.id}
                leading
                item={item}
                disabled={busyId !== null}
                onUndo={() => act(item, () => closeItem(item.id, 'reopen'), 'Open again')}
              />
            ))}
          </ListSection>
        ) : null}
      </ScrollView>

      <TodoEditorModal
        visible={isAdding}
        onClose={() => onAddingChange(false)}
        onSaved={() => {
          onAddingChange(false);
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

/** A section folded away until asked for: Show / Hide sits at the right of its header. */
function FoldSection({
  title,
  count,
  hint,
  open,
  onToggle,
  children,
}: {
  title: string;
  count: number;
  hint?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <ListSection
      header={`${title} · ${count}`}
      headerAction={
        <PressableScale
          onPress={onToggle}
          hitSlop={12}
          accessibilityRole="button"
          accessibilityState={{ expanded: open }}
          accessibilityLabel={`${open ? 'Hide' : 'Show'} ${title.toLowerCase()}`}>
          <AppText variant="footnote" color="tint" weight="600">
            {open ? 'Hide' : 'Show'}
          </AppText>
        </PressableScale>
      }
      footer={hint}>
      {open ? children : null}
    </ListSection>
  );
}

function TodoRow({
  item,
  today,
  stale,
  busy,
  locked,
  onToggle,
  onOpen,
  onMore,
}: {
  item: MemoryItem;
  today: string;
  stale: boolean;
  /** Work on this item is in flight. */
  busy: boolean;
  /** Work on some item is in flight; nothing else starts until it ends. */
  locked: boolean;
  onToggle: () => void;
  onOpen: () => void;
  onMore: () => void;
  /** Read by ListSection: insets the separator below this row past its circle. */
  leading?: boolean;
}) {
  const [pressed, setPressed] = useState(false);
  const [checked, setChecked] = useState(false);
  const [wasBusy, setWasBusy] = useState(busy);
  // Still on the list once the work is over: completing failed, so the circle empties.
  if (busy !== wasBusy) {
    setWasBusy(busy);
    if (!busy) setChecked(false);
  }

  const overdue = item.due_on !== null && item.due_on < today;
  const meta: { text: string; overdue?: boolean }[] = [];
  if (item.due_on) meta.push({ text: dueLabel(item.due_on, today), overdue });
  if (item.remind_at) meta.push({ text: `Reminder ${reminderLabel(item.remind_at)}` });
  if (stale) meta.push({ text: 'Gone quiet' });

  return (
    <Animated.View style={[styles.cell, pressed ? styles.cellPressed : styles.cellIdle]}>
      <CheckCircle
        checked={checked}
        busy={busy}
        disabled={locked}
        accessibilityLabel={`Mark ${item.content} done`}
        onPress={() => {
          setChecked(true);
          haptic.success();
          onToggle();
        }}
      />
      <Pressable
        style={styles.cellBody}
        onPress={onOpen}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button">
        <AppText variant="body" color={checked ? 'secondary' : 'primary'}>
          {item.title || item.content}
        </AppText>
        {meta.length ? (
          <AppText variant="footnote" color="secondary">
            {meta.map((part, index) => (
              <React.Fragment key={part.text}>
                {index > 0 ? ' · ' : ''}
                {part.overdue ? (
                  <AppText variant="footnote" color="destructive">
                    {part.text}
                  </AppText>
                ) : (
                  part.text
                )}
              </React.Fragment>
            ))}
          </AppText>
        ) : null}
      </Pressable>
      <IconButton
        icon={MoreHorizontalIcon}
        variant="plain"
        size={32}
        iconSize={20}
        color={Colors.secondaryLabel}
        onPress={onMore}
        accessibilityLabel="More actions"
      />
    </Animated.View>
  );
}

/**
 * The round check of a to-do. It shrinks a little under the finger, and on release fills
 * with the tint and shows a check (a 180 ms cross-fade; no scale with Reduce Motion).
 */
function CheckCircle({
  checked,
  busy,
  disabled,
  onPress,
  accessibilityLabel,
}: {
  checked: boolean;
  busy: boolean;
  disabled: boolean;
  onPress: () => void;
  accessibilityLabel: string;
}) {
  const [pressed, setPressed] = useState(false);
  const reducedMotion = useReducedMotion();
  return (
    <Pressable
      onPress={onPress}
      onPressIn={() => setPressed(true)}
      onPressOut={() => setPressed(false)}
      disabled={disabled || checked}
      hitSlop={{ top: 10, bottom: 10, left: 16, right: 8 }}
      pressRetentionOffset={16}
      accessibilityRole="checkbox"
      accessibilityState={{ checked, busy }}
      accessibilityLabel={accessibilityLabel}>
      <Animated.View style={[styles.circleBox, pressed && !reducedMotion && styles.circlePressed]}>
        {busy && !checked ? (
          <ActivityIndicator size="small" color={Colors.secondaryLabel} />
        ) : (
          <CheckMark checked={checked} />
        )}
      </Animated.View>
    </Pressable>
  );
}

function CheckMark({ checked }: { checked: boolean }) {
  const reducedMotion = useReducedMotion();
  return (
    <View style={styles.mark}>
      <View style={styles.ring} />
      <Animated.View
        style={[
          styles.fill,
          checked ? styles.fillOn : reducedMotion ? styles.fillOffStill : styles.fillOff,
        ]}>
        <HugeiconsIcon icon={Tick02Icon} size={14} color={Colors.white} strokeWidth={3} />
      </Animated.View>
    </View>
  );
}

function DoneRow({
  item,
  disabled,
  onUndo,
}: {
  item: MemoryItem;
  disabled: boolean;
  onUndo: () => void;
  /** Read by ListSection: insets the separator below this row past its circle. */
  leading?: boolean;
}) {
  return (
    <View style={[styles.cell, styles.cellIdle]}>
      <View style={styles.circleBox}>
        <CheckMark checked />
      </View>
      <AppText variant="body" color="secondary" numberOfLines={1} style={styles.cellBody}>
        {item.title || item.content}
      </AppText>
      <Button
        title="Undo"
        variant="plain"
        size="small"
        onPress={onUndo}
        disabled={disabled}
        containerStyle={styles.undo}
      />
    </View>
  );
}

function TriageRow({
  item,
  busy,
  onOpen,
  onKeep,
  onDone,
  onDrop,
}: {
  item: MemoryItem;
  busy: boolean;
  onOpen: () => void;
  onKeep: () => void;
  onDone: () => void;
  onDrop: () => void;
}) {
  const [pressed, setPressed] = useState(false);
  return (
    <Animated.View style={[styles.triageCell, pressed ? styles.cellPressed : styles.cellIdle]}>
      <Pressable
        onPress={onOpen}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button">
        <AppText variant="body">{item.title || item.content}</AppText>
      </Pressable>
      <View style={styles.triageActions}>
        {busy ? (
          <ActivityIndicator size="small" color={Colors.secondaryLabel} />
        ) : (
          <>
            <Button title="Keep" variant="tinted" size="small" haptic="light" onPress={onKeep} />
            <Button title="Done" variant="gray" size="small" haptic="success" onPress={onDone} />
            <Button title="Drop" variant="gray" size="small" haptic="light" onPress={onDrop} />
          </>
        )}
      </View>
    </Animated.View>
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
  // The last item stays on the sheet while it slides away.
  const [shown, setShown] = useState<MemoryItem | null>(item);
  if (item && item !== shown) setShown(item);
  const current = item ?? shown;
  const snoozes = snoozeChoices();
  const dues = today ? dueChoices(today) : [];

  return (
    <BottomSheet
      visible={item !== null}
      onClose={onClose}
      title={current ? current.title || current.content : undefined}
      rightAction={{ label: 'Done', onPress: onClose }}>
      {current ? (
        <>
          <ListSection header="Remind me">
            <View style={styles.choiceCell}>
              {snoozes.map((choice) => (
                <Button
                  key={choice.label}
                  title={choice.label}
                  variant="gray"
                  size="small"
                  haptic="light"
                  onPress={() =>
                    onChoose(
                      (target) => scheduleItem(target.id, { remind_at: choice.value }),
                      `Reminder ${reminderLabel(choice.value)}`
                    )
                  }
                />
              ))}
            </View>
          </ListSection>
          <ListSection header="Due">
            <View style={styles.choiceCell}>
              {dues.map((choice) => (
                <Button
                  key={choice.label}
                  title={choice.label}
                  variant="gray"
                  size="small"
                  haptic="light"
                  onPress={() =>
                    onChoose(
                      (target) => scheduleItem(target.id, { due_on: choice.value }),
                      `Due ${choice.label.toLowerCase()}`
                    )
                  }
                />
              ))}
              {current.due_on ? (
                <Button
                  title="No date"
                  variant="gray"
                  size="small"
                  haptic="light"
                  onPress={() =>
                    onChoose((target) => scheduleItem(target.id, { due_on: null }), 'No due date')
                  }
                />
              ) : null}
            </View>
          </ListSection>
          <ListSection>
            <ListRow title="Open" onPress={onOpen} />
            <ListRow
              title="Stop tracking"
              destructive
              accessory="none"
              onPress={() =>
                onChoose((target) => closeItem(target.id, 'drop'), 'No longer tracked')
              }
            />
          </ListSection>
        </>
      ) : null}
    </BottomSheet>
  );
}

const CIRCLE = 24;

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    paddingTop: 8,
    paddingBottom: 32,
  },
  spinner: {
    marginVertical: 32,
  },
  note: {
    marginHorizontal: ScreenMargin + 16,
    marginBottom: 28,
  },
  // A cell drawn like a ListRow: it highlights at once on touch down and fades out after.
  cell: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingLeft: 16,
    paddingRight: 8,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  cellPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  cellIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  cellBody: {
    flex: 1,
    paddingVertical: 11,
    gap: 2,
  },
  // 30 wide, like a ListRow's icon tile, so the text lines up with the rows around it.
  circleBox: {
    width: 30,
    height: 30,
    alignItems: 'center',
    justifyContent: 'center',
    transform: [{ scale: 1 }],
    transitionProperty: 'transform',
    transitionDuration: Motion.duration.press,
    transitionTimingFunction: Motion.css.easeOut,
  },
  circlePressed: {
    transform: [{ scale: 0.88 }],
  },
  mark: {
    width: CIRCLE,
    height: CIRCLE,
  },
  ring: {
    ...StyleSheet.absoluteFill,
    borderRadius: CIRCLE / 2,
    borderWidth: 1.5,
    borderColor: Colors.systemGray3,
  },
  fill: {
    ...StyleSheet.absoluteFill,
    borderRadius: CIRCLE / 2,
    backgroundColor: Colors.tint,
    alignItems: 'center',
    justifyContent: 'center',
    transitionProperty: ['opacity', 'transform'],
    transitionDuration: Motion.duration.small,
    transitionTimingFunction: Motion.css.easeOut,
  },
  fillOn: {
    opacity: 1,
    transform: [{ scale: 1 }],
  },
  fillOff: {
    opacity: 0,
    transform: [{ scale: 0.95 }],
  },
  fillOffStill: {
    opacity: 0,
    transform: [{ scale: 1 }],
  },
  undo: {
    marginRight: 8,
  },
  triageCell: {
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 10,
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  triageActions: {
    minHeight: 32,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  choiceCell: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    padding: 12,
  },
});

export default TodoPanel;
