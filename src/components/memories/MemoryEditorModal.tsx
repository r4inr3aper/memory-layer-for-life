/**
 * MemoryEditorModal Component
 *
 * Bottom sheet for writing a memory, correcting one, or saving one from a message Cooper
 * held back: the text, its kind, and whether it is sensitive (kept away from Cooper). The
 * caller does the saving; a failure is shown in the sheet so nothing typed is lost.
 */

import React, { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Cancel01Icon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { getErrorMessage } from '@/lib/api/client';
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
  const insets = useSafeAreaInsets();
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
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.overlay}>
          <TouchableWithoutFeedback onPress={handleClose}>
            <View style={styles.backdrop} />
          </TouchableWithoutFeedback>

          <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]}>
            <View style={styles.header}>
              <Text style={styles.title}>{title}</Text>
              <TouchableOpacity
                style={styles.closeBtn}
                onPress={handleClose}
                activeOpacity={0.7}
                accessibilityRole="button"
                accessibilityLabel="Close">
                <HugeiconsIcon icon={Cancel01Icon} size={18} color={Colors.iconMuted} />
              </TouchableOpacity>
            </View>

            <ScrollView
              style={styles.form}
              contentContainerStyle={styles.formContent}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}>
              <Text style={styles.label}>Memory</Text>
              <TextInput
                style={[styles.input, styles.multilineInput, error && styles.inputError]}
                value={draft.content}
                onChangeText={(content) => {
                  setDraft((current) => ({ ...current, content }));
                  setError(null);
                }}
                placeholder="My sister Priya lives in Pune"
                placeholderTextColor={Colors.iconMuted}
                maxLength={MEMORY_CONTENT_MAX_LENGTH}
                multiline
                textAlignVertical="top"
                autoFocus={Platform.OS !== 'web'}
                accessibilityLabel="Memory text"
              />
              {hint ? <Text style={styles.hintText}>{hint}</Text> : null}

              <Text style={styles.label}>Kind</Text>
              <View style={styles.chipRow}>
                {kinds.map((kind) => {
                  const selected = draft.memory_type === kind;
                  return (
                    <TouchableOpacity
                      key={kind}
                      style={[styles.chip, selected && styles.chipSelected]}
                      onPress={() => setDraft((current) => ({ ...current, memory_type: kind }))}
                      activeOpacity={0.75}
                      accessibilityRole="button"
                      accessibilityState={{ selected }}>
                      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>
                        {memoryTypeLabel(kind)}
                      </Text>
                    </TouchableOpacity>
                  );
                })}
              </View>

              <View style={styles.switchRow}>
                <View style={styles.switchText}>
                  <Text style={styles.switchTitle}>Sensitive</Text>
                  <Text style={styles.hintText}>
                    Health, feelings, or other private matters. You still see it here, but Cooper
                    never uses it.
                  </Text>
                </View>
                <Switch
                  value={draft.sensitive}
                  onValueChange={(sensitive) => setDraft((current) => ({ ...current, sensitive }))}
                  trackColor={{ false: Colors.border, true: Colors.primaryLight }}
                  thumbColor={draft.sensitive ? Colors.primary : Colors.surfaceMuted}
                  accessibilityLabel="Sensitive"
                />
              </View>

              {error ? (
                <View style={styles.submitErrorBox}>
                  <Text style={styles.submitErrorText}>{error}</Text>
                </View>
              ) : null}
            </ScrollView>

            <View style={styles.actionRow}>
              <TouchableOpacity
                style={styles.cancelBtn}
                onPress={handleClose}
                disabled={isSaving}
                activeOpacity={0.7}>
                <Text style={styles.cancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveBtn, isSaving && styles.saveBtnBusy]}
                onPress={handleSave}
                disabled={isSaving}
                activeOpacity={0.8}
                accessibilityRole="button">
                {isSaving ? (
                  <ActivityIndicator size="small" color={Colors.white} />
                ) : (
                  <Text style={styles.saveText}>{confirmText}</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  flex: {
    flex: 1,
  },
  overlay: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  backdrop: {
    ...StyleSheet.absoluteFill,
    backgroundColor: Colors.overlay,
  },
  sheet: {
    maxHeight: '90%',
    backgroundColor: Colors.white,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingTop: 18,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 20,
    marginBottom: 6,
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.iconDark,
    letterSpacing: -0.3,
  },
  closeBtn: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  form: {
    flexGrow: 0,
  },
  formContent: {
    paddingHorizontal: 20,
    paddingBottom: 12,
  },
  label: {
    fontSize: 11,
    fontWeight: '600',
    color: Colors.iconMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    marginTop: 16,
    marginBottom: 6,
  },
  input: {
    backgroundColor: Colors.surfaceInput,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    fontWeight: '500',
    color: Colors.iconDark,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
  },
  multilineInput: {
    minHeight: 96,
    paddingTop: 10,
  },
  inputError: {
    borderColor: Colors.error,
  },
  hintText: {
    marginTop: 6,
    fontSize: 12.5,
    lineHeight: 17,
    color: Colors.textSecondary,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: Colors.border,
    backgroundColor: Colors.white,
  },
  chipSelected: {
    borderColor: Colors.primaryBorder,
    backgroundColor: Colors.primarySubtle,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  chipTextSelected: {
    color: Colors.primary,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    marginTop: 18,
  },
  switchText: {
    flex: 1,
  },
  switchTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  submitErrorBox: {
    marginTop: 16,
    padding: 12,
    borderRadius: 12,
    backgroundColor: Colors.errorLight,
  },
  submitErrorText: {
    fontSize: 13,
    lineHeight: 18,
    color: Colors.error,
  },
  actionRow: {
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: 20,
    paddingTop: 10,
  },
  cancelBtn: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelText: {
    fontSize: 14,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  saveBtn: {
    flex: 1,
    height: 44,
    borderRadius: 22,
    backgroundColor: Colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveBtnBusy: {
    opacity: 0.75,
  },
  saveText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.white,
  },
});

export default MemoryEditorModal;
