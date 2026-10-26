/**
 * Review Cards
 *
 * The two kinds of review item that are not a single memory, each a white card on the
 * grouped background:
 *
 * - `SuggestionCard`: two memories that look like duplicates (merge them) or like they
 *   conflict (keep the newer one). Either way the user can keep both, and the pair is not
 *   suggested again.
 * - `HeldBackCard`: a message Cooper would not turn into a memory on its own. The user can
 *   save a memory from it, open the chat it came from, or dismiss it.
 *
 * Keeping taps a success haptic and discarding a light one, with the press that shows the
 * spinner. "Save as memory" only opens the editor, so it has none of its own.
 */

import React from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { HugeiconsIcon, type IconSvgElement } from '@hugeicons/react-native';
import { AlertCircleIcon, Copy01Icon, PauseIcon } from '@hugeicons/core-free-icons';
import { AppText, Button, Card, PressableScale } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Radius, continuous } from '@/constants/theme';
import type { HeldBack, MemoryItem, MemorySuggestion } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { heldBackReasonText, memoryTypeLabel, suggestionText } from '@/lib/memories';

export type SuggestionChoice = 'merge' | 'replace' | 'dismiss';

export function SuggestionCard({
  suggestion,
  busy,
  onChoose,
  onOpen,
}: {
  suggestion: MemorySuggestion;
  busy: boolean;
  onChoose: (choice: SuggestionChoice) => void;
  onOpen: (memory: MemoryItem) => void;
}) {
  const isDuplicate = suggestion.kind === 'duplicate';
  return (
    <Card>
      <Kicker
        icon={isDuplicate ? Copy01Icon : AlertCircleIcon}
        color={isDuplicate ? Colors.tint : Colors.systemOrange}
        label={isDuplicate ? 'Possible duplicate' : 'Possible conflict'}
      />
      <AppText variant="subheadline" color="secondary" style={styles.explain}>
        {suggestionText(suggestion.kind)}
      </AppText>
      <View style={styles.pair}>
        <PairMemory label="Older" memory={suggestion.first} onPress={onOpen} />
        <PairMemory label="Newer" memory={suggestion.second} onPress={onOpen} />
      </View>
      <View style={styles.actionRow}>
        {busy ? (
          <ActivityIndicator color={Colors.systemGray} />
        ) : (
          <>
            <Button
              title={isDuplicate ? 'Merge' : 'Keep newer'}
              variant="tinted"
              size="small"
              haptic="success"
              onPress={() => onChoose(isDuplicate ? 'merge' : 'replace')}
            />
            <Button
              title="Keep both"
              variant="gray"
              size="small"
              haptic="light"
              onPress={() => onChoose('dismiss')}
            />
          </>
        )}
      </View>
    </Card>
  );
}

function Kicker({ icon, color, label }: { icon: IconSvgElement; color: string; label: string }) {
  return (
    <View style={styles.kicker}>
      <HugeiconsIcon icon={icon} size={15} color={color} strokeWidth={2} />
      <AppText variant="footnote" weight="600" color={color} style={styles.kickerText} numberOfLines={1}>
        {label}
      </AppText>
    </View>
  );
}

function PairMemory({
  label,
  memory,
  onPress,
}: {
  label: string;
  memory: MemoryItem;
  onPress: (memory: MemoryItem) => void;
}) {
  return (
    <PressableScale
      onPress={() => onPress(memory)}
      pressedScale={0.98}
      accessibilityRole="button"
      accessibilityHint="Opens the memory"
      style={[styles.pairMemory, continuous]}>
      <AppText variant="footnote" color="secondary">
        {label} · {memoryTypeLabel(memory.memory_type)} · {formatRelativeTime(memory.created_at)}
      </AppText>
      <AppText variant="body">{memory.content}</AppText>
    </PressableScale>
  );
}

export function HeldBackCard({
  heldBack,
  busy,
  onSave,
  onDismiss,
  onOpenChat,
}: {
  heldBack: HeldBack;
  busy: boolean;
  onSave: () => void;
  onDismiss: () => void;
  onOpenChat: ((threadId: string) => void) | null;
}) {
  const threadId = heldBack.messages.find((message) => message.thread_id)?.thread_id ?? null;
  return (
    <Card>
      <Kicker
        icon={PauseIcon}
        color={Colors.systemOrange}
        label={`Held back${heldBack.held_at ? ` · ${formatRelativeTime(heldBack.held_at)}` : ''}`}
      />
      <AppText variant="subheadline" color="secondary" style={styles.explain}>
        {heldBackReasonText(heldBack.reason)}
      </AppText>
      {heldBack.messages.map((message) => (
        <View key={message.raw_message_id} style={styles.quote}>
          <View style={styles.quoteRule} />
          <AppText variant="body" style={styles.quoteText}>
            “{message.content}”
          </AppText>
        </View>
      ))}
      {threadId && onOpenChat ? (
        <Button
          title="Open the chat"
          variant="plain"
          size="small"
          onPress={() => onOpenChat(threadId)}
          containerStyle={styles.openChat}
        />
      ) : null}
      <View style={styles.actionRow}>
        {busy ? (
          <ActivityIndicator color={Colors.systemGray} />
        ) : (
          <>
            <Button title="Save as memory" variant="tinted" size="small" onPress={onSave} />
            <Button title="Dismiss" variant="gray" size="small" haptic="light" onPress={onDismiss} />
          </>
        )}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  kicker: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  kickerText: {
    flexShrink: 1,
  },
  explain: {
    marginTop: 4,
  },
  pair: {
    marginTop: 12,
    gap: 8,
  },
  pairMemory: {
    gap: 2,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: Radius.md - 2,
    backgroundColor: Colors.groupedBackground,
  },
  quote: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 12,
  },
  quoteRule: {
    width: 3,
    borderRadius: 1.5,
    backgroundColor: Colors.systemGray4,
  },
  quoteText: {
    flex: 1,
  },
  openChat: {
    alignSelf: 'flex-start',
    marginTop: 6,
    marginLeft: -4,
  },
  // Keeps its height while the spinner stands in for the buttons, so nothing jumps.
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
    minHeight: 32,
    marginTop: 14,
  },
});
