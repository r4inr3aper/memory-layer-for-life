/**
 * AttachmentChips Component
 *
 * Removable chips above the chat composer for the files attached to the next message:
 * a glyph, the file's name and size on a light gray tile, and a small round remove button.
 */

import { AppText, IconButton } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Radius, continuous } from '@/constants/theme';
import type { PendingAttachment } from '@/lib/attachmentPicker';
import { formatFileSize } from '@/lib/attachments';
import { Cancel01Icon, Image01Icon, Pdf01Icon } from '@hugeicons/core-free-icons';
import { HugeiconsIcon } from '@hugeicons/react-native';
import React from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

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
        <View key={attachment.id} style={[styles.chip, continuous]}>
          <HugeiconsIcon
            icon={attachment.media_type === 'application/pdf' ? Pdf01Icon : Image01Icon}
            size={18}
            color={Colors.tint}
            strokeWidth={2}
          />
          <View style={styles.chipText}>
            <AppText variant="footnote" weight="600" numberOfLines={1}>
              {attachment.name}
            </AppText>
            <AppText variant="caption2" color="secondary">
              {formatFileSize(attachment.size)}
            </AppText>
          </View>
          <IconButton
            icon={Cancel01Icon}
            variant="filled"
            size={22}
            iconSize={12}
            color={Colors.secondaryLabel}
            style={styles.removeBtn}
            onPress={() => onRemove(attachment.id)}
            accessibilityLabel={`Remove ${attachment.name}`}
          />
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
    gap: 8,
    maxWidth: 220,
    paddingLeft: 10,
    paddingRight: 6,
    paddingVertical: 7,
    borderRadius: Radius.md,
    backgroundColor: Colors.groupedBackground,
  },
  chipText: {
    flexShrink: 1,
  },
  removeBtn: {
    // A step darker than the tile, so the button reads on it.
    backgroundColor: Colors.fill,
  },
});

export default AttachmentChips;
