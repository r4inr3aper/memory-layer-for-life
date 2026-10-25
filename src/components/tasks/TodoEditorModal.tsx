/**
 * TodoEditorModal Component
 *
 * Bottom sheet for adding a to-do: what to do, what kind it is, when it is due (quick
 * choices or a date), and an optional reminder at a date and time. The item is saved as a
 * memory written by the user, so Cooper knows about it too.
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
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Colors } from '@/constants/colors';
import { getErrorMessage } from '@/lib/api/client';
import { createMemory } from '@/lib/api/memories';
import type { MemoryItem } from '@/lib/api/types';
import { dueChoices, isoDate, localIsoTime } from '@/lib/life';
import { MEMORY_CONTENT_MAX_LENGTH, validateMemoryContent } from '@/lib/memories';
import { DateField, TimeField } from './DateTimeFields';

const KINDS = [
  { value: 'task', label: 'To-do' },
  { value: 'plan', label: 'Plan' },
  { value: 'goal', label: 'Goal' },
] as const;

export interface TodoEditorModalProps {
  visible: boolean;
  onClose: () => void;
  onSaved: (item: MemoryItem) => void;
}

export const TodoEditorModal: React.FC<TodoEditorModalProps> = ({ visible, onClose, onSaved }) => {
  const insets = useSafeAreaInsets();
  const today = isoDate(new Date());
  const [content, setContent] = useState('');
  const [kind, setKind] = useState<string>('task');
  const [dueOn, setDueOn] = useState<string | null>(null);
  const [isPickingDate, setIsPickingDate] = useState(false);
  const [remind, setRemind] = useState(false);
  const [remindDate, setRemindDate] = useState(today);
  const [remindTime, setRemindTime] = useState('09:00');
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [wasVisible, setWasVisible] = useState(visible);

  // A fresh form each time the sheet opens.
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setContent('');
      setKind('task');
      setDueOn(null);
      setIsPickingDate(false);
      setRemind(false);
      setRemindDate(today);
      setRemindTime('09:00');
      setError(null);
    }
  }

  const handleSave = async () => {
    const problem = validateMemoryContent(content);
    if (problem) {
      setError(problem.replace('Write what Cooper should remember.', 'Write what to do.'));
      return;
    }
    const remindAt = remind ? localIsoTime(remindDate, remindTime) : null;
    if (remindAt && new Date(remindAt).getTime() <= Date.now()) {
      setError('Pick a reminder time in the future.');
      return;
    }
    setIsSaving(true);
    setError(null);
    try {
      const saved = await createMemory({
        memory_type: kind,
        content: content.trim(),
        due_on: dueOn,
        remind_at: remindAt,
      });
      onSaved(saved);
    } catch (saveError) {
      setError(getErrorMessage(saveError, 'Could not save it'));
    } finally {
      setIsSaving(false);
    }
  };

  const choices = dueChoices(today);

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={styles.overlay}>
          <TouchableWithoutFeedback onPress={isSaving ? undefined : onClose}>
            <View style={styles.backdrop} />
          </TouchableWithoutFeedback>
          <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 16) }]}>
            <Text style={styles.title}>New to-do</Text>
            <ScrollView
              style={styles.form}
              contentContainerStyle={styles.formContent}
              keyboardShouldPersistTaps="handled">
              <TextInput
                style={[styles.input, error && styles.inputError]}
                value={content}
                onChangeText={(text) => {
                  setContent(text);
                  setError(null);
                }}
                placeholder="Renew the passport"
                placeholderTextColor={Colors.iconMuted}
                maxLength={MEMORY_CONTENT_MAX_LENGTH}
                autoFocus={Platform.OS !== 'web'}
                accessibilityLabel="What to do"
              />

              <Text style={styles.label}>Kind</Text>
              <View style={styles.chipRow}>
                {KINDS.map((option) => (
                  <Chip
                    key={option.value}
                    label={option.label}
                    selected={kind === option.value}
                    onPress={() => setKind(option.value)}
                  />
                ))}
              </View>

              <Text style={styles.label}>Due</Text>
              <View style={styles.chipRow}>
                <Chip
                  label="No date"
                  selected={dueOn === null && !isPickingDate}
                  onPress={() => {
                    setDueOn(null);
                    setIsPickingDate(false);
                  }}
                />
                {choices.map((choice) => (
                  <Chip
                    key={choice.label}
                    label={choice.label}
                    selected={dueOn === choice.value && !isPickingDate}
                    onPress={() => {
                      setDueOn(choice.value);
                      setIsPickingDate(false);
                    }}
                  />
                ))}
                <Chip
                  label="Pick a date"
                  selected={isPickingDate}
                  onPress={() => {
                    setIsPickingDate(true);
                    setDueOn(dueOn ?? today);
                  }}
                />
              </View>
              {isPickingDate ? (
                <View style={styles.fieldSpacing}>
                  <DateField
                    value={dueOn ?? today}
                    onChange={setDueOn}
                    accessibilityLabel="Due date"
                  />
                </View>
              ) : null}

              <View style={styles.switchRow}>
                <Text style={styles.switchTitle}>Remind me</Text>
                <Switch
                  value={remind}
                  onValueChange={(value) => {
                    setRemind(value);
                    if (value && dueOn) setRemindDate(dueOn);
                  }}
                  trackColor={{ false: Colors.border, true: Colors.primaryLight }}
                  thumbColor={remind ? Colors.primary : Colors.surfaceMuted}
                  accessibilityLabel="Remind me"
                />
              </View>
              {remind ? (
                <View style={[styles.chipRow, styles.fieldSpacing]}>
                  <DateField
                    value={remindDate}
                    onChange={setRemindDate}
                    accessibilityLabel="Reminder date"
                  />
                  <TimeField
                    value={remindTime}
                    onChange={setRemindTime}
                    accessibilityLabel="Reminder time"
                  />
                </View>
              ) : null}

              {error ? <Text style={styles.errorText}>{error}</Text> : null}
            </ScrollView>

            <View style={styles.actionRow}>
              <TouchableOpacity style={styles.cancelBtn} onPress={onClose} disabled={isSaving}>
                <Text style={styles.cancelText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={styles.saveBtn}
                onPress={handleSave}
                disabled={isSaving}
                accessibilityRole="button">
                {isSaving ? (
                  <ActivityIndicator size="small" color={Colors.white} />
                ) : (
                  <Text style={styles.saveText}>Add</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

function Chip({
  label,
  selected,
  onPress,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.chip, selected && styles.chipSelected]}
      onPress={onPress}
      activeOpacity={0.75}
      accessibilityRole="button"
      accessibilityState={{ selected }}>
      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text>
    </TouchableOpacity>
  );
}

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
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: Colors.iconDark,
    paddingHorizontal: 20,
    marginBottom: 10,
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
  inputError: {
    borderColor: Colors.error,
  },
  errorText: {
    marginTop: 10,
    fontSize: 12.5,
    color: Colors.error,
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
  fieldSpacing: {
    marginTop: 10,
  },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 18,
  },
  switchTitle: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
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
  saveText: {
    fontSize: 14,
    fontWeight: '700',
    color: Colors.white,
  },
});

export default TodoEditorModal;
