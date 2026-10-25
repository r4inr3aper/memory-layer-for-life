/**
 * Review Cards
 *
 * The two kinds of review item that are not a single memory:
 *
 * - `SuggestionCard`: two memories that look like duplicates (merge them) or like they
 *   conflict (keep the newer one). Either way the user can keep both, and the pair is not
 *   suggested again.
 * - `HeldBackCard`: a message Cooper would not turn into a memory on its own. The user can
 *   save a memory from it, open the chat it came from, or dismiss it.
 */

import React from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { Colors } from '@/constants/colors';
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
    <View style={styles.card}>
      <Text style={styles.kicker}>{isDuplicate ? 'Possible duplicate' : 'Possible conflict'}</Text>
      <Text style={styles.explain}>{suggestionText(suggestion.kind)}</Text>
      <PairMemory label="Older" memory={suggestion.first} onPress={onOpen} />
      <PairMemory label="Newer" memory={suggestion.second} onPress={onOpen} />
      {busy ? (
        <ActivityIndicator style={styles.busy} color={Colors.primary} />
      ) : (
        <View style={styles.actionRow}>
          <CardButton
            label={isDuplicate ? 'Merge' : 'Keep newer'}
            primary
            onPress={() => onChoose(isDuplicate ? 'merge' : 'replace')}
          />
          <CardButton label="Keep both" onPress={() => onChoose('dismiss')} />
        </View>
      )}
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
    <TouchableOpacity
      style={styles.pairMemory}
      onPress={() => onPress(memory)}
      activeOpacity={0.7}
      accessibilityRole="button"
      accessibilityHint="Opens the memory">
      <Text style={styles.pairLabel}>
        {label} · {memoryTypeLabel(memory.memory_type)} · {formatRelativeTime(memory.created_at)}
      </Text>
      <Text style={styles.pairContent}>{memory.content}</Text>
    </TouchableOpacity>
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
    <View style={styles.card}>
      <Text style={styles.kicker}>
        Held back{heldBack.held_at ? ` · ${formatRelativeTime(heldBack.held_at)}` : ''}
      </Text>
      <Text style={styles.explain}>{heldBackReasonText(heldBack.reason)}</Text>
      {heldBack.messages.map((message) => (
        <Text key={message.raw_message_id} style={styles.quote}>
          “{message.content}”
        </Text>
      ))}
      {threadId && onOpenChat ? (
        <TouchableOpacity onPress={() => onOpenChat(threadId)} activeOpacity={0.7}>
          <Text style={styles.linkText}>Open the chat</Text>
        </TouchableOpacity>
      ) : null}
      {busy ? (
        <ActivityIndicator style={styles.busy} color={Colors.primary} />
      ) : (
        <View style={styles.actionRow}>
          <CardButton label="Save as memory" primary onPress={onSave} />
          <CardButton label="Dismiss" onPress={onDismiss} />
        </View>
      )}
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
    padding: 14,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
    marginBottom: 10,
  },
  kicker: {
    fontSize: 11,
    fontWeight: '700',
    color: Colors.primary,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  explain: {
    marginTop: 4,
    fontSize: 13.5,
    lineHeight: 19,
    color: Colors.textSecondary,
  },
  pairMemory: {
    marginTop: 10,
    padding: 10,
    borderRadius: 12,
    backgroundColor: Colors.surface,
  },
  pairLabel: {
    fontSize: 11.5,
    fontWeight: '600',
    color: Colors.iconMuted,
  },
  pairContent: {
    marginTop: 3,
    fontSize: 14.5,
    lineHeight: 20,
    color: Colors.textPrimary,
  },
  quote: {
    marginTop: 10,
    fontSize: 14.5,
    lineHeight: 20,
    fontStyle: 'italic',
    color: Colors.textPrimary,
  },
  linkText: {
    marginTop: 8,
    fontSize: 13,
    fontWeight: '600',
    color: Colors.primary,
  },
  busy: {
    marginTop: 14,
  },
  actionRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
  },
  button: {
    height: 36,
    paddingHorizontal: 14,
    borderRadius: 18,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  buttonPrimary: {
    backgroundColor: Colors.primary,
  },
  buttonText: {
    fontSize: 13.5,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  buttonTextPrimary: {
    color: Colors.white,
  },
});
