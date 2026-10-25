/**
 * Life Cards
 *
 * Cards under Cooper's proactive messages:
 *
 * - `ReminderCard`, under a reminder the user set: Done, or snooze for an hour or until
 *   tomorrow morning.
 * - `BriefCard`, under the daily brief: Done or Not yet beside each item that was due
 *   yesterday and is still open ("Not yet" moves it to today), and a link to the list.
 *
 * Each card calls the API itself and remembers what the user chose while the chat is open.
 */

import React, { useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useRouter } from 'expo-router';
import { Colors } from '@/constants/colors';
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
    <View style={styles.card}>
      {outcome ? (
        <Text style={styles.outcome}>{outcome.label}</Text>
      ) : busy ? (
        <ActivityIndicator color={Colors.primary} />
      ) : (
        <View style={styles.actions}>
          <CardButton
            label="Done"
            primary
            onPress={() =>
              act(async () => {
                await closeItem(note.memory_id, 'complete');
                return 'Marked done';
              })
            }
          />
          <CardButton label="In 1 hour" onPress={() => snooze('In 1 hour')} />
          <CardButton label="Tomorrow" onPress={() => snooze('Tomorrow morning')} />
        </View>
      )}
      <TouchableOpacity
        onPress={() => router.push({ pathname: '/memories/[id]', params: { id: note.memory_id } })}
        activeOpacity={0.7}>
        <Text style={styles.link}>Open</Text>
      </TouchableOpacity>
    </View>
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
    <View style={styles.card}>
      {note.follow_ups.map((item) => (
        <View key={item.memory_id} style={styles.followUp}>
          <Text style={styles.followUpText} numberOfLines={2}>
            {item.content}
          </Text>
          {outcomes[item.memory_id] ? (
            <Text style={styles.outcome}>{outcomes[item.memory_id]}</Text>
          ) : busyId === item.memory_id ? (
            <ActivityIndicator color={Colors.primary} />
          ) : (
            <View style={styles.actions}>
              <CardButton
                label="Done"
                primary
                onPress={() =>
                  act(item.memory_id, async () => {
                    await closeItem(item.memory_id, 'complete');
                    return 'Done';
                  })
                }
              />
              <CardButton
                label="Not yet"
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
      <TouchableOpacity onPress={() => router.navigate('/(tabs)/tasks')} activeOpacity={0.7}>
        <Text style={styles.link}>See your list</Text>
      </TouchableOpacity>
    </View>
  );
}

function CardButton({
  label,
  onPress,
  primary = false,
}: {
  label: string;
  onPress: () => void;
  primary?: boolean;
}) {
  return (
    <TouchableOpacity
      style={[styles.button, primary && styles.buttonPrimary]}
      onPress={onPress}
      activeOpacity={0.8}
      accessibilityRole="button">
      <Text style={[styles.buttonText, primary && styles.buttonTextPrimary]}>{label}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  card: {
    marginTop: 10,
    padding: 12,
    borderRadius: 14,
    backgroundColor: Colors.white,
    borderWidth: 1,
    borderColor: Colors.border,
    gap: 8,
  },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  followUp: {
    gap: 6,
    paddingBottom: 8,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderLight,
  },
  followUpText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  outcome: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.success,
  },
  link: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  button: {
    height: 32,
    paddingHorizontal: 12,
    borderRadius: 16,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPrimary: {
    backgroundColor: Colors.primary,
  },
  buttonText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  buttonTextPrimary: {
    color: Colors.white,
  },
});
