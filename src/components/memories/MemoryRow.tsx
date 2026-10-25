/**
 * MemoryRow Component
 *
 * One memory in a list: its text, kind, when it was saved, and markers for what needs the
 * user's attention (to review, sensitive, written by the user). Tapping opens the memory.
 * Lists that review memories pass `onAccept` and `onRetract` for quick buttons.
 */

import React from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { Cancel01Icon, LockIcon, Tick02Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import type { MemoryItem } from '@/lib/api/types';
import { formatRelativeTime } from '@/lib/formatTime';
import { memoryStatusLabel, memoryTypeLabel } from '@/lib/memories';

export interface MemoryRowProps {
  memory: MemoryItem;
  onPress: () => void;
  onAccept?: () => void;
  onRetract?: () => void;
  /** A quick action is being saved. */
  busy?: boolean;
}

export const MemoryRow: React.FC<MemoryRowProps> = ({
  memory,
  onPress,
  onAccept,
  onRetract,
  busy = false,
}) => {
  const meta = [memoryTypeLabel(memory.memory_type), formatRelativeTime(memory.created_at)];
  if (memory.created_by === 'user') meta.push('Written by you');

  return (
    <View style={styles.row}>
      <TouchableOpacity
        style={styles.body}
        onPress={onPress}
        activeOpacity={0.7}
        accessibilityRole="button"
        accessibilityHint="Opens the memory">
        <Text style={styles.content} numberOfLines={3}>
          {memory.content}
        </Text>
        <View style={styles.metaRow}>
          {memory.sensitive ? (
            <HugeiconsIcon
              icon={LockIcon}
              size={12}
              color={Colors.iconMuted}
              accessibilityLabel="Sensitive"
            />
          ) : null}
          <Text style={styles.meta}>{meta.join(' · ')}</Text>
          {memory.status !== 'active' ? (
            <View style={[styles.pill, styles[`pill_${memory.status}`]]}>
              <Text style={styles.pillText}>{memoryStatusLabel(memory.status)}</Text>
            </View>
          ) : null}
        </View>
      </TouchableOpacity>

      {onAccept || onRetract ? (
        <View style={styles.actions}>
          {busy ? (
            <ActivityIndicator size="small" color={Colors.primary} />
          ) : (
            <>
              {onRetract ? (
                <TouchableOpacity
                  style={[styles.quickButton, styles.quickRetract]}
                  onPress={onRetract}
                  hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                  accessibilityRole="button"
                  accessibilityLabel="Mark as wrong">
                  <HugeiconsIcon icon={Cancel01Icon} size={16} color={Colors.error} />
                </TouchableOpacity>
              ) : null}
              {onAccept ? (
                <TouchableOpacity
                  style={[styles.quickButton, styles.quickAccept]}
                  onPress={onAccept}
                  hitSlop={{ top: 6, bottom: 6, left: 6, right: 6 }}
                  accessibilityRole="button"
                  accessibilityLabel="Accept">
                  <HugeiconsIcon icon={Tick02Icon} size={16} color={Colors.success} />
                </TouchableOpacity>
              ) : null}
            </>
          )}
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  body: {
    flex: 1,
    paddingVertical: 13,
  },
  content: {
    fontSize: 15,
    lineHeight: 21,
    color: Colors.textPrimary,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 5,
  },
  meta: {
    fontSize: 12.5,
    color: Colors.chartAxisText,
  },
  pill: {
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 8,
  },
  pill_proposed: {
    backgroundColor: Colors.primarySubtle,
  },
  pill_active: {
    backgroundColor: Colors.successLight,
  },
  pill_superseded: {
    backgroundColor: Colors.surface,
  },
  pill_retracted: {
    backgroundColor: Colors.errorLight,
  },
  pillText: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  actions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    minWidth: 40,
    justifyContent: 'flex-end',
  },
  quickButton: {
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: 'center',
    justifyContent: 'center',
  },
  quickAccept: {
    backgroundColor: Colors.successLight,
  },
  quickRetract: {
    backgroundColor: Colors.errorLight,
  },
});

export default MemoryRow;
