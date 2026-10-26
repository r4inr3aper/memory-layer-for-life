/**
 * TodaySection Component
 *
 * The top of the Feed: what to do now, from what the user told their assistant
 * (`GET /me/today`), each group something to act on, laid out as Reminders lays out its
 * lists (inset-grouped sections on the grouped background):
 * - Next up: overdue, due or reminded today, promises, then this week. Tick to finish.
 * - Promises: open items that involve people.
 * - Coming up: today's and tomorrow's calendar events, with what is known about the
 *   people in them.
 * - Still on?: one idea or goal noted weeks ago and untouched since; plan it in chat.
 * - Is this right?: the newest memories the assistant was unsure of; yes or no.
 * Reloads when the Feed is shown and when `refreshKey` changes (pull to refresh).
 *
 * A tick fills its circle with the tint at once (a CSS transition on opacity and scale,
 * with a light haptic in the same frame) and stays filled while the server closes the
 * item; the item then leaves with the reload, or the circle empties again on failure.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import Animated, { useReducedMotion } from 'react-native-reanimated';
import { useFocusEffect, useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import {
  AlertCircleIcon,
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  Tick02Icon,
} from '@hugeicons/core-free-icons';
import {
  AppText,
  Button,
  Card,
  EmptyState,
  IconTile,
  ListRow,
  ListSection,
  PressableScale,
} from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Motion, ScreenMargin } from '@/constants/theme';
import { useAgentProfile } from '@/context/AgentProfileContext';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { closeItem } from '@/lib/api/life';
import { changeMemoryStatus } from '@/lib/api/memories';
import { getToday } from '@/lib/api/today';
import type { MemoryItem, TodayCards } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { haptic } from '@/lib/haptics';
import { dueLabel } from '@/lib/life';
import { openChatWithPrefill } from '@/lib/navigation';

// Row metrics, matching ListRow so text and separators line up across the groups: text
// starts past a 30 pt leading slot, which is where ListSection insets the separator under
// a row that has `leading`.
const ROW_PADDING = 16;
const ROW_PADDING_VERTICAL = 11;
const LEADING_SLOT = 30;
const LEADING_GAP = 14;
const TEXT_INSET = ROW_PADDING + LEADING_SLOT + LEADING_GAP;
// The body text style's line height: leading controls center on the first line.
const FIRST_LINE = 22;
const CHECK_SIZE = 22;
const CHECK_RING = 1.5;
const MIN_TARGET = 44;
const COULD_NOT_LOAD = "Couldn't load today";

export function TodaySection({ refreshKey = 0 }: { refreshKey?: number }) {
  const router = useRouter();
  const { profile } = useAgentProfile();
  const [cards, setCards] = useState<TodayCards | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback((signal?: AbortSignal) => {
    return getToday(signal)
      .then((loaded) => {
        setCards(loaded);
        setError(null);
      })
      .catch((loadError) => {
        if (isAbortError(loadError, signal)) return;
        setError(getErrorMessage(loadError, COULD_NOT_LOAD));
      });
  }, []);

  useFocusEffect(
    useCallback(() => {
      const controller = new AbortController();
      void load(controller.signal);
      return () => controller.abort();
    }, [load])
  );

  useEffect(() => {
    if (refreshKey > 0) void load();
  }, [refreshKey, load]);

  const act = async (memoryId: string, work: () => Promise<unknown>, message: string) => {
    if (busyId) return;
    setBusyId(memoryId);
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

  const open = (memory: MemoryItem) =>
    router.push({ pathname: '/memories/[id]', params: { id: memory.id } });

  if (error && !cards) {
    return (
      <Card style={styles.stateCard}>
        <EmptyState
          compact
          icon={AlertCircleIcon}
          title={COULD_NOT_LOAD}
          message={error !== COULD_NOT_LOAD ? error : undefined}
          actionTitle="Try again"
          onAction={() => void load()}
          style={styles.stateContent}
        />
      </Card>
    );
  }
  if (!cards) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={Colors.systemGray} />
      </View>
    );
  }

  const isClear =
    cards.next_actions.length === 0 &&
    cards.promises.length === 0 &&
    cards.meetings.length === 0 &&
    cards.resurface === null &&
    cards.to_confirm.length === 0;

  // A to-do: the round check, then the title and when it is due. Returned as the Row
  // element itself, so ListSection sees its `leading` and insets the separator past it.
  const todo = (memory: MemoryItem, extra?: string) => {
    const meta = [memory.due_on ? dueLabel(memory.due_on, cards.today) : null, extra]
      .filter(Boolean)
      .join(' · ');
    const overdue = memory.due_on !== null && memory.due_on < cards.today;
    const busy = busyId === memory.id;
    return (
      <Row
        key={memory.id}
        leading={
          <RoundCheck
            checked={busy}
            disabled={busyId !== null}
            onPress={() => {
              haptic.light();
              void act(memory.id, () => closeItem(memory.id, 'complete'), 'Done');
            }}
            accessibilityState={{ checked: false, busy }}
            accessibilityLabel={`Mark ${memory.title} done`}
          />
        }
        onPress={() => open(memory)}>
        <AppText variant="body" numberOfLines={3} color={busy ? 'secondary' : 'primary'}>
          {memory.title || memory.content}
        </AppText>
        {meta ? (
          <AppText variant="footnote" color={overdue ? 'destructive' : 'secondary'}>
            {meta}
          </AppText>
        ) : null}
      </Row>
    );
  };

  const resurface = cards.resurface;

  return (
    <View>
      {isClear ? (
        <Card style={styles.stateCard}>
          <EmptyState
            compact
            icon={CheckmarkCircle02Icon}
            title="You're clear for now"
            message={`Tell ${profile.name} what's on your mind, and what needs doing shows up here.`}
            style={styles.stateContent}
          />
        </Card>
      ) : null}

      {cards.next_actions.length ? (
        <ListSection header="Next up">{cards.next_actions.map((memory) => todo(memory))}</ListSection>
      ) : null}

      {cards.promises.length ? (
        <ListSection header="Promises">
          {cards.promises.map(({ memory, people }) => todo(memory, `with ${people.join(', ')}`))}
        </ListSection>
      ) : null}

      {cards.meetings.length ? (
        <ListSection header="Coming up">
          {cards.meetings.flatMap(({ event, people, related }) => [
            <ListRow
              key={event.id}
              icon={Calendar03Icon}
              iconColor={Colors.systemRed}
              title={event.title || event.content}
              subtitle={event.due_on ? dueLabel(event.due_on, cards.today) : undefined}
              numberOfLines={2}
              accessory="none"
              onPress={() => open(event)}
            />,
            people.length && related.length ? (
              <RelatedNotes
                key={`${event.id}-related`}
                people={people}
                related={related}
                onOpen={open}
              />
            ) : null,
          ])}
        </ListSection>
      ) : null}

      {resurface ? (
        <ListSection header="Still on?">
          {/* One cell: the item, then its actions, with no separator between them. */}
          <View>
            <Row
              leading={<IconTile icon={Clock01Icon} color={Colors.systemOrange} />}
              leadingSize={LEADING_SLOT}
              onPress={() => open(resurface)}>
              <AppText variant="body" numberOfLines={3}>
                {resurface.title || resurface.content}
              </AppText>
              <AppText variant="footnote" color="secondary">
                You noted this {formatRelativeTime(resurface.created_at)}
              </AppText>
            </Row>
            <View style={styles.resurfaceActions}>
              <Button
                title={`Plan it with ${profile.name}`}
                variant="tinted"
                size="small"
                onPress={() =>
                  openChatWithPrefill(
                    `Help me take the next step on this: ${resurface.title || resurface.content}`
                  )
                }
              />
              <Button title="Open" variant="gray" size="small" onPress={() => open(resurface)} />
            </View>
          </View>
        </ListSection>
      ) : null}

      {cards.to_confirm.length ? (
        <ListSection header="Is this right?" footer={`${profile.name} wasn't sure about these.`}>
          {cards.to_confirm.map((memory) => (
            <Row
              key={memory.id}
              onPress={() => open(memory)}
              trailing={
                busyId === memory.id ? (
                  <View style={styles.confirmBusy}>
                    <ActivityIndicator size="small" color={Colors.systemGray} />
                  </View>
                ) : (
                  <View style={styles.confirmButtons}>
                    <Button
                      title="Yes"
                      variant="tinted"
                      size="small"
                      haptic="light"
                      disabled={busyId !== null}
                      onPress={() =>
                        act(memory.id, () => changeMemoryStatus(memory.id, 'accept'), 'Kept')
                      }
                      accessibilityLabel={`Yes, keep ${memory.title}`}
                    />
                    <Button
                      title="No"
                      variant="gray"
                      size="small"
                      haptic="light"
                      disabled={busyId !== null}
                      onPress={() =>
                        act(
                          memory.id,
                          () => changeMemoryStatus(memory.id, 'retract'),
                          `${profile.name} won't use it`
                        )
                      }
                      accessibilityLabel={`No, forget ${memory.title}`}
                    />
                  </View>
                )
              }>
              <AppText variant="body" numberOfLines={4}>
                {memory.title || memory.content}
              </AppText>
            </Row>
          ))}
          {cards.review_count > cards.to_confirm.length ? (
            <ListRow
              title={`${cards.review_count - cards.to_confirm.length} more this week in To review`}
              onPress={() => router.push({ pathname: '/memories', params: { tab: 'review' } })}
            />
          ) : null}
        </ListSection>
      ) : null}
    </View>
  );
}

// --- Rows ------------------------------------------------------------------------------

interface RowProps {
  /** A control or glyph before the text (the round check); a control is its own target. */
  leading?: React.ReactNode;
  /** Height of the leading element, to center it on the first line of text. */
  leadingSize?: number;
  /** Controls after the text (Yes / No); their own touch targets. */
  trailing?: React.ReactNode;
  onPress: () => void;
  children: React.ReactNode;
}

/**
 * A cell of a Today group. The text opens the item; the controls beside it are separate
 * buttons (separate for VoiceOver too, which is why they are siblings, not children, of
 * the text's pressable). The whole cell highlights while the text is pressed, as a list
 * cell does: at once on touch down, fading out after release. Cells do not scale.
 */
function Row({ leading, leadingSize = CHECK_SIZE, trailing, onPress, children }: RowProps) {
  const [pressed, setPressed] = useState(false);
  return (
    <Animated.View style={[styles.row, pressed ? styles.rowPressed : styles.rowIdle]}>
      {leading ? (
        <View
          style={[
            styles.leadingSlot,
            { paddingTop: ROW_PADDING_VERTICAL + (FIRST_LINE - leadingSize) / 2 },
          ]}>
          {leading}
        </View>
      ) : null}
      <Pressable
        style={[styles.rowBody, !leading && styles.rowBodyPlain, !trailing && styles.rowBodyLast]}
        onPress={onPress}
        onPressIn={() => setPressed(true)}
        onPressOut={() => setPressed(false)}
        unstable_pressDelay={40}
        pressRetentionOffset={16}
        accessibilityRole="button">
        {children}
      </Pressable>
      {trailing ? <View style={styles.trailing}>{trailing}</View> : null}
    </Animated.View>
  );
}

interface RoundCheckProps {
  checked: boolean;
  disabled: boolean;
  onPress: () => void;
  accessibilityLabel: string;
  accessibilityState: { checked: boolean; busy: boolean };
}

/**
 * Reminders' completion circle: an empty ring that fills with the tint and a white tick.
 * The fill grows from 60% as it fades in, over 180 ms on the strong ease-out (a CSS
 * transition between two states; no worklet). With Reduce Motion it only fades. The
 * circle dips under the finger on press-in. 22 pt visual, 44 pt touch target.
 */
function RoundCheck({
  checked,
  disabled,
  onPress,
  accessibilityLabel,
  accessibilityState,
}: RoundCheckProps) {
  const [pressed, setPressed] = useState(false);
  const reducedMotion = useReducedMotion();
  const slop = (MIN_TARGET - CHECK_SIZE) / 2;
  return (
    <Pressable
      onPress={onPress}
      onPressIn={() => setPressed(true)}
      onPressOut={() => setPressed(false)}
      disabled={disabled}
      hitSlop={{ top: slop, bottom: slop, left: slop, right: slop }}
      pressRetentionOffset={16}
      accessibilityRole="checkbox"
      accessibilityState={accessibilityState}
      accessibilityLabel={accessibilityLabel}>
      <Animated.View style={[styles.check, pressed && !reducedMotion && styles.checkPressed]}>
        <View style={styles.checkRing} />
        <Animated.View
          style={[
            styles.checkFill,
            checked
              ? styles.checkFillOn
              : reducedMotion
                ? styles.checkFillOffStill
                : styles.checkFillOff,
          ]}>
          <HugeiconsIcon icon={Tick02Icon} size={14} color={Colors.white} strokeWidth={3} />
        </Animated.View>
      </Animated.View>
    </Pressable>
  );
}

/** Under a meeting: what the user has said about the people in it. */
function RelatedNotes({
  people,
  related,
  onOpen,
}: {
  people: string[];
  related: MemoryItem[];
  onOpen: (memory: MemoryItem) => void;
}) {
  return (
    <View style={styles.related}>
      <AppText variant="footnote" color="secondary" style={styles.relatedTitle}>
        What you&apos;ve said about {people.join(', ')}
      </AppText>
      {related.map((memory) => (
        <PressableScale
          key={memory.id}
          onPress={() => onOpen(memory)}
          accessibilityRole="button"
          style={styles.relatedItem}>
          <AppText variant="subheadline" color="tertiary">
            •
          </AppText>
          <AppText variant="subheadline" numberOfLines={2} style={styles.relatedText}>
            {memory.title || memory.content}
          </AppText>
        </PressableScale>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  loading: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 32,
    marginBottom: 12,
  },
  stateCard: {
    marginHorizontal: ScreenMargin,
    marginBottom: 28,
  },
  stateContent: {
    paddingVertical: 12,
  },
  row: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    transitionProperty: 'backgroundColor',
    transitionTimingFunction: 'ease-out',
  },
  // Highlight at once on touch down; fade out after release (as ListRow does).
  rowPressed: {
    backgroundColor: Colors.cellPressed,
    transitionDuration: 0,
  },
  rowIdle: {
    backgroundColor: Colors.secondaryGroupedBackground,
    transitionDuration: 350,
  },
  leadingSlot: {
    width: LEADING_SLOT,
    marginLeft: ROW_PADDING,
    marginRight: LEADING_GAP,
    alignItems: 'center',
    alignSelf: 'flex-start',
  },
  rowBody: {
    flex: 1,
    gap: 2,
    paddingVertical: ROW_PADDING_VERTICAL,
  },
  rowBodyPlain: {
    paddingLeft: ROW_PADDING,
  },
  rowBodyLast: {
    paddingRight: ROW_PADDING,
  },
  trailing: {
    paddingLeft: 12,
    paddingRight: ROW_PADDING,
  },
  check: {
    width: CHECK_SIZE,
    height: CHECK_SIZE,
    transform: [{ scale: 1 }],
    transitionProperty: 'transform',
    transitionDuration: Motion.duration.press,
    transitionTimingFunction: Motion.css.easeOut,
  },
  checkPressed: {
    transform: [{ scale: 0.88 }],
  },
  checkRing: {
    ...StyleSheet.absoluteFill,
    borderRadius: CHECK_SIZE / 2,
    borderWidth: CHECK_RING,
    borderColor: Colors.systemGray3,
  },
  checkFill: {
    ...StyleSheet.absoluteFill,
    borderRadius: CHECK_SIZE / 2,
    backgroundColor: Colors.tint,
    alignItems: 'center',
    justifyContent: 'center',
    transitionProperty: ['opacity', 'transform'],
    transitionDuration: Motion.duration.small,
    transitionTimingFunction: Motion.css.easeOut,
  },
  checkFillOn: {
    opacity: 1,
    transform: [{ scale: 1 }],
  },
  checkFillOff: {
    opacity: 0,
    transform: [{ scale: 0.6 }],
  },
  checkFillOffStill: {
    opacity: 0,
    transform: [{ scale: 1 }],
  },
  related: {
    paddingLeft: TEXT_INSET,
    paddingRight: ROW_PADDING,
    paddingTop: 10,
    paddingBottom: 8,
  },
  relatedTitle: {
    marginBottom: 2,
  },
  relatedItem: {
    flexDirection: 'row',
    gap: 6,
    paddingVertical: 4,
  },
  relatedText: {
    flex: 1,
  },
  resurfaceActions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    paddingLeft: TEXT_INSET,
    paddingRight: ROW_PADDING,
    paddingTop: 2,
    paddingBottom: 14,
  },
  confirmButtons: {
    flexDirection: 'row',
    gap: 8,
  },
  confirmBusy: {
    minWidth: MIN_TARGET,
    alignItems: 'center',
  },
});
