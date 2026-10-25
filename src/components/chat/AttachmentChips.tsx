/**
 * AttachmentChips Component
 *
 * Removable chips above the chat input for the files attached to the next message.
 */

import { Colors } from '@/constants/colors';
import type { PendingAttachment } from '@/lib/attachmentPicker';
import { formatFileSize } from '@/lib/attachments';
import { Cancel01Icon, Image01Icon, Pdf01Icon } from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import React from 'react';
import { ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';

export interface AttachmentChipsProps {
  attachments: PendingAttachment[];
  onRemove: (id: string) => void;
}

export function AttachmentChips({ attachments, onRemove }: AttachmentChipsProps) {
  if (attachments.length === 0) {
    return null;
  }

  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      style={styles.scroll}
      contentContainerStyle={styles.row}>
      {attachments.map((attachment) => (
        <View key={attachment.id} style={styles.chip}>
          <HugeiconsIcon
            icon={attachment.media_type === 'application/pdf' ? Pdf01Icon : Image01Icon}
            size={16}
            color={Colors.primary}
            strokeWidth={2}
          />
          <View style={styles.chipText}>
            <Text style={styles.chipName} numberOfLines={1}>
              {attachment.name}
            </Text>
            <Text style={styles.chipSize}>{formatFileSize(attachment.size)}</Text>
          </View>
          <TouchableOpacity
            style={styles.removeBtn}
            onPress={() => onRemove(attachment.id)}
            hitSlop={{ top: 8, bottom: 8, left: 8, right: 8 }}
            accessibilityRole="button"
            accessibilityLabel={`Remove ${attachment.name}`}>
            <HugeiconsIcon icon={Cancel01Icon} size={14} color={Colors.iconMuted} strokeWidth={2.2} />
          </TouchableOpacity>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: {
    flexGrow: 0,
    marginBottom: 8,
  },
  row: {
    gap: 8,
  },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    maxWidth: 220,
    paddingLeft: 10,
    paddingRight: 6,
    paddingVertical: 6,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
    backgroundColor: Colors.inputBarBg,
    gap: 8,
  },
  chipText: {
    flexShrink: 1,
  },
  chipName: {
    fontSize: 12.5,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  chipSize: {
    fontSize: 11,
    color: Colors.iconMuted,
    marginTop: 1,
  },
  removeBtn: {
    width: 22,
    height: 22,
    borderRadius: 11,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.white,
  },
});

export default AttachmentChips;
