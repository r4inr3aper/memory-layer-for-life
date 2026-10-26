/**
 * Life Cards
 *
 * Cards under Cooper's proactive messages, as iOS cards on the white chat (grouped gray,
 * continuous corners, small capsule buttons):
 *
 * - `ReminderCard`, under a reminder the user set: Done, or snooze for an hour or until
 *   tomorrow morning.
 * - `BriefCard`, under the daily brief: Done or Not yet beside each item that was due
 *   yesterday and is still open ("Not yet" moves it to today), and a link to the list.
 *
 * Each card calls the API itself and remembers what the user chose while the chat is open.
 */

import React, { useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Tick02Icon } from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { AppText, Button, Card } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Hairline } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage } from '@/lib/api/client';
import { closeItem, scheduleItem } from '@/lib/api/life';
import type { BriefNote, ReminderNote } from '@/lib/api/types';
import { isoDate, reminderLabel, snoozeChoices } from '@/lib/life';

type Outcome = { label: string } | null;

async function attempt(work: () => Promise<string>): Promise<Outcome> {
  try {
    return { label: await work() };
  } catch (error) {
    showToast(getErrorMessage(error, 'Something went wrong'), 3500);
    return null;
  }
}

export function ReminderCard({ note }: { note: ReminderNote }) {
  const router = useRouter();
  const [outcome, setOutcome] = useState<Outcome>(null);
  const [busy, setBusy] = useState(false);

  const act = async (work: () => Promise<string>) => {
    if (busy) return;
    setBusy(true);
    setOutcome(await attempt(work));
    setBusy(false);
  };

  // Computed when pressed: a card read hours later must not snooze into the past.
  const snooze = (label: string) =>
    act(async () => {
      const choice = snoozeChoices().find((option) => option.label === label);
      if (!choice) throw new Error('That snooze is not available now.');
      await scheduleItem(note.memory_id, { remind_at: choice.value });
      return `Snoozed until ${reminderLabel(choice.value)}`;
    });

  return (
    <Card style={styles.card}>
      {outcome ? (
        <OutcomeLine label={outcome.label} />
      ) : busy ? (
        <ActivityIndicator color={Colors.tint} style={styles.spinner} />
      ) : (
        <View style={styles.actions}>
          <Button
            title="Done"
            size="small"
            onPress={() =>
              act(async () => {
                await closeItem(note.memory_id, 'complete');
                return 'Marked done';
              })
            }
          />
          <Button
            title="In 1 hour"
            variant="tinted"
            size="small"
            onPress={() => snooze('In 1 hour')}
          />
          <Button
            title="Tomorrow"
            variant="tinted"
            size="small"
            onPress={() => snooze('Tomorrow morning')}
          />
        </View>
      )}
      <Button
        title="Open"
        variant="plain"
        size="small"
        containerStyle={styles.link}
        onPress={() => router.push({ pathname: '/memories/[id]', params: { id: note.memory_id } })}
      />
    </Card>
  );
}

export function BriefCard({ note }: { note: BriefNote }) {
  const router = useRouter();
  const [outcomes, setOutcomes] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const act = async (memoryId: string, work: () => Promise<string>) => {
    if (busyId) return;
    setBusyId(memoryId);
    const outcome = await attempt(work);
    if (outcome) setOutcomes((current) => ({ ...current, [memoryId]: outcome.label }));
    setBusyId(null);
  };

  return (
    <Card style={styles.card}>
      {note.follow_ups.map((item, index) => (
        <View key={item.memory_id} style={[styles.followUp, index > 0 && styles.followUpDivided]}>
          <AppText variant="subheadline" weight="600" numberOfLines={2}>
            {item.content}
          </AppText>
          {outcomes[item.memory_id] ? (
            <OutcomeLine label={outcomes[item.memory_id]} />
          ) : busyId === item.memory_id ? (
            <ActivityIndicator color={Colors.tint} style={styles.spinner} />
          ) : (
            <View style={styles.actions}>
              <Button
                title="Done"
                size="small"
                onPress={() =>
                  act(item.memory_id, async () => {
                    await closeItem(item.memory_id, 'complete');
                    return 'Done';
                  })
                }
              />
              <Button
                title="Not yet"
                variant="tinted"
                size="small"
                onPress={() =>
                  act(item.memory_id, async () => {
                    await scheduleItem(item.memory_id, { due_on: isoDate(new Date()) });
                    return 'Moved to today';
                  })
                }
              />
            </View>
          )}
        </View>
      ))}
      <Button
        title="See your list"
        variant="plain"
        size="small"
        containerStyle={styles.link}
        onPress={() => router.navigate('/(tabs)/tasks')}
      />
    </Card>
  );
}

/** What the user chose, in place of the buttons. */
function OutcomeLine({ label }: { label: string }) {
  return (
    <View style={styles.outcome}>
      <HugeiconsIcon icon={Tick02Icon} size={16} color={Colors.systemGreen} strokeWidth={2.2} />
      <AppText variant="subheadline" weight="600" color="success" style={styles.outcomeText}>
        {label}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: Colors.groupedBackground,
    padding: 14,
    gap: 10,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  followUp: {
    gap: 8,
  },
  followUpDivided: {
    paddingTop: 10,
    borderTopWidth: Hairline,
    borderTopColor: Colors.separator,
  },
  outcome: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    minHeight: 32,
  },
  outcomeText: {
    flexShrink: 1,
  },
  spinner: {
    alignSelf: 'flex-start',
    minHeight: 32,
  },
  link: {
    alignSelf: 'flex-start',
    // The plain button's label lines up with the card's text.
    marginLeft: -4,
    marginVertical: -4,
  },
});
