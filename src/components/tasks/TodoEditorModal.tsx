/**
 * TodoEditorModal Component
 *
 * Bottom sheet for adding a to-do: what to do, what kind it is, when it is due (quick
 * choices or a date), and an optional reminder at a date and time. The item is saved as a
 * memory written by the user, so Cooper knows about it too.
 */

import React, { useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { AppSwitch } from '@/components/ui/AppSwitch';
import { AppText } from '@/components/ui/AppText';
import { BottomSheet } from '@/components/ui/BottomSheet';
import { ListRow, ListSection } from '@/components/ui/List';
import { SegmentedControl } from '@/components/ui/SegmentedControl';
import { getErrorMessage } from '@/lib/api/client';
import { createMemory } from '@/lib/api/memories';
import type { MemoryItem } from '@/lib/api/types';
import { dueChoices, isoDate, localIsoTime } from '@/lib/life';
import { MEMORY_CONTENT_MAX_LENGTH, validateMemoryContent } from '@/lib/memories';
import { ChoiceChip, DateField, FieldTextInput, TimeField } from './DateTimeFields';

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
    <BottomSheet
      visible={visible}
      onClose={onClose}
      dismissible={!isSaving}
      title="New to-do"
      leftAction={{ label: 'Cancel', onPress: onClose, disabled: isSaving }}
      rightAction={{ label: 'Add', onPress: handleSave, loading: isSaving }}
      scrollable>
      <ListSection
        footer={
          error ? (
            <AppText variant="footnote" color="destructive">
              {error}
            </AppText>
          ) : undefined
        }>
        <FieldTextInput
          value={content}
          onChangeText={(text) => {
            setContent(text);
            setError(null);
          }}
          placeholder="Renew the passport"
          maxLength={MEMORY_CONTENT_MAX_LENGTH}
          autoFocus={Platform.OS !== 'web'}
          returnKeyType="done"
          accessibilityLabel="What to do"
        />
      </ListSection>

      <ListSection header="Kind">
        <View style={styles.cell}>
          <SegmentedControl segments={KINDS} value={kind} onChange={setKind} />
        </View>
      </ListSection>

      <ListSection header="Due">
        <View style={[styles.cell, styles.chips]}>
          <ChoiceChip
            label="No date"
            selected={dueOn === null && !isPickingDate}
            onPress={() => {
              setDueOn(null);
              setIsPickingDate(false);
            }}
          />
          {choices.map((choice) => (
            <ChoiceChip
              key={choice.label}
              label={choice.label}
              selected={dueOn === choice.value && !isPickingDate}
              onPress={() => {
                setDueOn(choice.value);
                setIsPickingDate(false);
              }}
            />
          ))}
          <ChoiceChip
            label="Pick a date"
            selected={isPickingDate}
            onPress={() => {
              setIsPickingDate(true);
              setDueOn(dueOn ?? today);
            }}
          />
        </View>
        {isPickingDate ? (
          <DateField
            label="Date"
            value={dueOn ?? today}
            onChange={setDueOn}
            accessibilityLabel="Due date"
          />
        ) : null}
      </ListSection>

      <ListSection>
        <ListRow
          title="Remind me"
          accessory={
            <AppSwitch
              value={remind}
              onValueChange={(value) => {
                setRemind(value);
                if (value && dueOn) setRemindDate(dueOn);
              }}
              accessibilityLabel="Remind me"
            />
          }
        />
        {remind ? (
          <DateField
            label="Date"
            value={remindDate}
            onChange={setRemindDate}
            accessibilityLabel="Reminder date"
          />
        ) : null}
        {remind ? (
          <TimeField
            label="Time"
            value={remindTime}
            onChange={setRemindTime}
            accessibilityLabel="Reminder time"
          />
        ) : null}
      </ListSection>
    </BottomSheet>
  );
};

const styles = StyleSheet.create({
  cell: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
});

export default TodoEditorModal;
