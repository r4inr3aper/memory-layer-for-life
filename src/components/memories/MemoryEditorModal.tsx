/**
 * MemoryEditorModal Component
 *
 * Bottom sheet for writing a memory, correcting one, or saving one from a message Cooper
 * held back: the text, its kind, and whether it is sensitive (kept away from Cooper). The
 * caller does the saving; a failure is shown in the sheet so nothing typed is lost.
 *
 * An iOS form sheet: Cancel at the left of the title bar, the save action in bold at the
 * right, and each field in a white cell with no border on the grouped background.
 */

import React, { useState } from 'react';
import { Platform, StyleSheet, TextInput, View } from 'react-native';
// Straight from their files: the barrel also exports the screen header (expo-router).
import { AppSwitch } from '@/components/ui/AppSwitch';
import { AppText } from '@/components/ui/AppText';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { ListRow, ListSection } from '@/components/ui/List';
import { PressableScale } from '@/components/ui/PressableScale';
import { Colors } from '@/constants/colors';
import { Radius, Typography, continuous } from '@/constants/theme';
import { getErrorMessage } from '@/lib/api/client';
import { haptic } from '@/lib/haptics';
import {
  MEMORY_CONTENT_MAX_LENGTH,
  MEMORY_TYPE_CHOICES,
  memoryTypeLabel,
  validateMemoryContent,
} from '@/lib/memories';

export interface MemoryDraft {
  content: string;
  memory_type: string;
  sensitive: boolean;
}

export interface MemoryEditorModalProps {
  visible: boolean;
  title: string;
  confirmText: string;
  /** What the sheet opens with. */
  initial: MemoryDraft;
  /** Shown under the text field, e.g. that new text makes a new version. */
  hint?: string;
  onClose: () => void;
  /** Saves the draft; a thrown error is shown in the sheet. */
  onSubmit: (draft: MemoryDraft) => Promise<void>;
}

export const MemoryEditorModal: React.FC<MemoryEditorModalProps> = ({
  visible,
  title,
  confirmText,
  initial,
  hint,
  onClose,
  onSubmit,
}) => {
  const [draft, setDraft] = useState<MemoryDraft>(initial);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [wasVisible, setWasVisible] = useState(visible);

  // Start from the given values each time the sheet opens.
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setDraft(initial);
      setError(null);
      setIsSaving(false);
    }
  }

  const handleClose = () => {
    if (!isSaving) onClose();
  };

  const handleSave = async () => {
    const problem = validateMemoryContent(draft.content);
    if (problem) {
      setError(problem);
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      await onSubmit({ ...draft, content: draft.content.trim() });
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Could not save the memory'));
    } finally {
      setIsSaving(false);
    }
  };

  // The kinds offered, plus the memory's own kind when it is not among them.
  const kinds: string[] = [...MEMORY_TYPE_CHOICES];
  if (!kinds.includes(draft.memory_type)) kinds.unshift(draft.memory_type);

  return (
    <BottomSheet
      visible={visible}
      onClose={handleClose}
      dismissible={!isSaving}
      title={title}
      leftAction={{ label: 'Cancel', onPress: handleClose, disabled: isSaving }}
      rightAction={{ label: confirmText, onPress: handleSave, loading: isSaving }}
      scrollable>
      <ListSection
        footer={
          error || hint ? (
            <View style={styles.footer}>
              {error ? (
                <AppText variant="footnote" color="destructive">
                  {error}
                </AppText>
              ) : null}
              {hint ? (
                <AppText variant="footnote" color="secondary">
                  {hint}
                </AppText>
              ) : null}
            </View>
          ) : undefined
        }>
        <TextInput
          style={styles.input}
          value={draft.content}
          onChangeText={(content) => {
            setDraft((current) => ({ ...current, content }));
            setError(null);
          }}
          placeholder="My sister Priya lives in Pune"
          placeholderTextColor={Colors.placeholder}
          selectionColor={Colors.tint}
          maxLength={MEMORY_CONTENT_MAX_LENGTH}
          multiline
          textAlignVertical="top"
          autoFocus={Platform.OS !== 'web'}
          accessibilityLabel="Memory text"
        />
      </ListSection>

      <ListSection header="Kind">
        <View style={styles.kinds}>
          {kinds.map((kind) => {
            const selected = draft.memory_type === kind;
            return (
              <PressableScale
                key={kind}
                onPress={() => {
                  if (!selected) haptic.selection();
                  setDraft((current) => ({ ...current, memory_type: kind }));
                }}
                accessibilityRole="button"
                accessibilityState={{ selected }}
                style={[styles.capsule, continuous, selected && styles.capsuleSelected]}>
                <AppText variant="subheadline" weight="500" color={selected ? 'inverse' : 'primary'}>
                  {memoryTypeLabel(kind)}
                </AppText>
              </PressableScale>
            );
          })}
        </View>
      </ListSection>

      <ListSection footer="Health, feelings, or other private matters. You still see it here, but Cooper never uses it.">
        <ListRow
          title="Sensitive"
          accessory={
            <AppSwitch
              value={draft.sensitive}
              onValueChange={(sensitive) => setDraft((current) => ({ ...current, sensitive }))}
              accessibilityLabel="Sensitive"
            />
          }
        />
      </ListSection>
    </BottomSheet>
  );
};

const styles = StyleSheet.create({
  input: {
    ...Typography.body,
    minHeight: 112,
    paddingHorizontal: 16,
    paddingTop: 12,
    paddingBottom: 12,
    color: Colors.label,
  },
  footer: {
    gap: 4,
  },
  kinds: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    padding: 12,
  },
  // iOS filter capsules: a gray fill, the selected one in the tint with white text.
  capsule: {
    height: 32,
    paddingHorizontal: 14,
    borderRadius: Radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: Colors.tertiaryFill,
  },
  capsuleSelected: {
    backgroundColor: Colors.tint,
  },
});

export default MemoryEditorModal;
