/**
 * ScheduleFormModal Component
 *
 * Bottom sheet for creating a schedule (Tasks tab "+ New") or editing one (schedule detail
 * "Edit"): title, task, how often (once, daily, chosen weekdays, monthly, every few hours)
 * at a time picked with the platform's picker, and where results go. Only chat and the
 * apps the user has connected are offered as destinations.
 *
 * New schedules use the phone's timezone; an edited one keeps its own unless the user
 * switches it to the phone's.
 */

import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';
import { useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { MinusSignIcon, PlusSignIcon } from '@hugeicons/core-free-icons';
import { AppText, BottomSheet, ListRow, ListSection } from '@/components/ui';
import { Colors } from '@/constants/colors';
import { Hairline, Radius, continuous } from '@/constants/theme';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { createSchedule, updateSchedule } from '@/lib/api/schedules';
import { listTools } from '@/lib/api/tools';
import type { Schedule, ScheduleDelivery, Weekday } from '@/lib/api/types';
import { deviceTimezone, formatTimezone, ordinal } from '@/lib/formatSchedule';
import { haptic } from '@/lib/haptics';
import {
  availableDeliveries,
  DELIVERY_OPTIONS,
  DELIVERY_TARGET_MAX_LENGTH,
  FREQUENCY_OPTIONS,
  MAX_INTERVAL_HOURS,
  MIN_INTERVAL_HOURS,
  newScheduleValues,
  SCHEDULE_TASK_MAX_LENGTH,
  SCHEDULE_TITLE_MAX_LENGTH,
  scheduleToValues,
  validateScheduleEdit,
  validateScheduleForm,
  WEEKDAY_PRESETS,
  WEEKDAYS,
  type ScheduleFormErrors,
  type ScheduleFormField,
  type ScheduleFormValues,
} from '@/lib/scheduleForm';
import { ChoiceChip, DateField, FieldTextInput, TimeField } from './DateTimeFields';

export interface ScheduleFormModalProps {
  visible: boolean;
  /** The schedule to edit. Without one, the form creates a schedule. */
  schedule?: Schedule | null;
  onClose: () => void;
  /** Called with the created or edited schedule; the modal closes itself. */
  onSaved: (schedule: Schedule) => void;
}

export const ScheduleFormModal: React.FC<ScheduleFormModalProps> = ({
  visible,
  schedule,
  onClose,
  onSaved,
}) => {
  const router = useRouter();
  const isEditing = Boolean(schedule);
  const phoneTimezone = deviceTimezone();

  const [values, setValues] = useState<ScheduleFormValues>(() => newScheduleValues());
  const [timezone, setTimezone] = useState(phoneTimezone);
  const [errors, setErrors] = useState<ScheduleFormErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  // null until the connected apps are known; then chat plus each connected app.
  const [deliveries, setDeliveries] = useState<Set<ScheduleDelivery> | null>(null);

  // Fill the form each time the sheet opens: empty for a new schedule, or the schedule's.
  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setValues(schedule ? scheduleToValues(schedule) : newScheduleValues());
      setTimezone(schedule?.timezone ?? phoneTimezone);
      setErrors({});
      setSubmitError(null);
      setDeliveries(null);
    }
  }

  // Which apps can receive results, checked each time the sheet opens.
  useEffect(() => {
    if (!visible) return;
    const controller = new AbortController();
    listTools(controller.signal)
      .then((tools) => setDeliveries(availableDeliveries(tools)))
      .catch((error) => {
        if (isAbortError(error, controller.signal)) return;
        console.warn('[schedules] Could not load connected apps:', error);
        // Offer every destination; the backend still refuses an unconnected one.
        setDeliveries(new Set(DELIVERY_OPTIONS.map((option) => option.value)));
      });
    return () => controller.abort();
  }, [visible]);

  const update = (changes: Partial<ScheduleFormValues>, ...fields: ScheduleFormField[]) => {
    setValues((current) => ({ ...current, ...changes }));
    if (fields.length) {
      setErrors((current) => {
        const next = { ...current };
        for (const field of fields) delete next[field];
        return next;
      });
    }
  };

  const toggleWeekday = (day: Weekday) =>
    update(
      {
        weekdays: values.weekdays.includes(day)
          ? values.weekdays.filter((selected) => selected !== day)
          : [...values.weekdays, day],
      },
      'weekdays'
    );

  const handleClose = () => {
    if (!isSaving) onClose();
  };

  const openConnections = () => {
    onClose();
    router.push('/tools');
  };

  const handleSave = async () => {
    if (isSaving) return;
    const context = { timezone, deliveries: deliveries ?? undefined };
    let send: () => Promise<Schedule>;
    if (schedule) {
      const result = validateScheduleEdit(values, schedule, context);
      if (!result.ok) return setErrors(result.errors);
      send = () => updateSchedule(schedule.id, result.body);
    } else {
      const result = validateScheduleForm(values, context);
      if (!result.ok) return setErrors(result.errors);
      send = () => createSchedule(result.body);
    }

    setErrors({});
    setSubmitError(null);
    setIsSaving(true);
    try {
      const saved = await send();
      showToast(schedule ? 'Schedule updated' : 'Schedule created');
      onSaved(saved);
      onClose();
    } catch (error) {
      console.error('Failed to save schedule:', error);
      const message = getErrorMessage(
        error,
        schedule ? 'Could not save the schedule' : 'Could not create the schedule'
      );
      setSubmitError(message);
      showToast(message);
    } finally {
      setIsSaving(false);
    }
  };

  const deliveryOption = DELIVERY_OPTIONS.find((option) => option.value === values.delivery);
  const runsPerDay = Math.ceil(24 / Math.max(values.intervalHours, 1));
  const isInterval = values.frequency === 'interval';

  return (
    // The sheet itself always closes when dragged or tapped outside: a save in flight
    // still finishes and reports through the toast.
    <BottomSheet
      visible={visible}
      onClose={onClose}
      dismissible={!isSaving}
      title={isEditing ? 'Edit schedule' : 'New schedule'}
      leftAction={{ label: 'Cancel', onPress: handleClose, disabled: isSaving }}
      rightAction={{
        label: isEditing ? 'Save' : 'Create',
        onPress: handleSave,
        loading: isSaving,
      }}
      detent="large"
      scrollable
      contentStyle={styles.content}>
      {submitError ? (
        <AppText variant="footnote" color="destructive" style={styles.submitError}>
          {submitError}
        </AppText>
      ) : null}

      <ListSection header="Title" footer={errorFooter(errors.title)}>
        <FieldTextInput
          value={values.title}
          onChangeText={(title) => update({ title }, 'title')}
          placeholder="Morning inbox summary"
          maxLength={SCHEDULE_TITLE_MAX_LENGTH}
          returnKeyType="next"
          accessibilityLabel="Title"
        />
      </ListSection>

      <ListSection header="Task" footer={errorFooter(errors.task)}>
        <FieldTextInput
          value={values.task}
          onChangeText={(task) => update({ task }, 'task')}
          placeholder="Summarize my unread emails and list anything that needs a reply."
          maxLength={SCHEDULE_TASK_MAX_LENGTH}
          multiline
          accessibilityLabel="Task"
        />
      </ListSection>

      <ListSection header="Repeats">
        {FREQUENCY_OPTIONS.map((option) => {
          const selected = values.frequency === option.value;
          return (
            <ListRow
              key={option.value}
              title={option.label}
              accessory={selected ? 'check' : 'none'}
              accessibilityLabel={selected ? `${option.label}, selected` : option.label}
              onPress={() =>
                update(
                  { frequency: option.value },
                  'date',
                  'weekdays',
                  'dayOfMonth',
                  'intervalHours'
                )
              }
            />
          );
        })}
      </ListSection>

      {values.frequency === 'weekly' ? (
        <ListSection header="Days" footer={errorFooter(errors.weekdays)}>
          <View style={[styles.cell, styles.chips]}>
            {WEEKDAY_PRESETS.map((preset) => (
              <ChoiceChip
                key={preset.label}
                label={preset.label}
                selected={
                  preset.days.length === values.weekdays.length &&
                  preset.days.every((day) => values.weekdays.includes(day))
                }
                onPress={() => update({ weekdays: [...preset.days] }, 'weekdays')}
              />
            ))}
          </View>
          <View style={[styles.cell, styles.days]}>
            {WEEKDAYS.map((day) => (
              <ChoiceChip
                key={day.value}
                label={day.label}
                selected={values.weekdays.includes(day.value)}
                multiSelect
                onPress={() => toggleWeekday(day.value)}
                containerStyle={styles.dayChipContainer}
                style={styles.dayChip}
              />
            ))}
          </View>
        </ListSection>
      ) : null}

      <ListSection
        header="When"
        footer={
          <View style={styles.footerLines}>
            <FieldError message={errors.date} />
            <FieldError message={errors.dayOfMonth} />
            <FieldError message={errors.intervalHours} />
            <FieldError message={errors.time} />
            {values.frequency === 'monthly' && values.dayOfMonth >= 29 ? (
              <AppText variant="footnote" color="secondary">
                Months without a {ordinal(values.dayOfMonth)} run on their last day.
              </AppText>
            ) : null}
            {isInterval ? (
              <AppText variant="footnote" color="secondary">
                About {runsPerDay} {runsPerDay === 1 ? 'run' : 'runs'} a day; each uses one of
                your daily prompts.
              </AppText>
            ) : null}
            <AppText variant="footnote" color="secondary">
              Times are in {formatTimezone(timezone)} ({timezone}).
            </AppText>
          </View>
        }>
        {values.frequency === 'once' ? (
          <DateField
            label="Date"
            value={values.date}
            onChange={(date) => update({ date }, 'date')}
            hasError={Boolean(errors.date)}
            accessibilityLabel="Date"
          />
        ) : null}
        {values.frequency === 'monthly' ? (
          <StepperRow
            label="Day of the month"
            value={values.dayOfMonth}
            min={1}
            max={31}
            format={(day) => String(day)}
            onChange={(dayOfMonth) => update({ dayOfMonth }, 'dayOfMonth')}
            accessibilityLabel="Day of the month"
          />
        ) : null}
        {isInterval ? (
          <StepperRow
            label="Every"
            value={values.intervalHours}
            min={MIN_INTERVAL_HOURS}
            max={MAX_INTERVAL_HOURS}
            format={(hours) => (hours === 1 ? '1 hour' : `${hours} hours`)}
            onChange={(intervalHours) => update({ intervalHours }, 'intervalHours')}
            accessibilityLabel="Hours between runs"
          />
        ) : null}
        <TimeField
          label={isInterval ? 'Starting at' : 'Time'}
          value={values.time}
          onChange={(time) => update({ time }, 'time', 'date')}
          hasError={Boolean(errors.time)}
          accessibilityLabel="Time"
        />
        {timezone !== phoneTimezone ? (
          <ListRow
            title={`Use this phone's timezone (${formatTimezone(phoneTimezone)})`}
            action
            numberOfLines={2}
            onPress={() => setTimezone(phoneTimezone)}
          />
        ) : null}
      </ListSection>

      <ListSection
        header="Send results to"
        headerAction={
          deliveries === null ? <ActivityIndicator size="small" color={Colors.secondaryLabel} /> : null
        }
        footer={
          <View style={styles.footerLines}>
            <FieldError message={errors.delivery} />
            <Pressable
              onPress={openConnections}
              accessibilityRole="link"
              hitSlop={8}
              style={({ pressed }) => pressed && styles.linkPressed}>
              <AppText variant="footnote" color="secondary">
                Only connected apps can receive results.{' '}
                <AppText variant="footnote" color="tint">
                  Manage connections
                </AppText>
              </AppText>
            </Pressable>
            {values.delivery === 'chat' ? (
              <AppText variant="footnote" color="secondary">
                {isEditing && schedule?.source_thread_id
                  ? 'Results are posted to the chat this schedule came from.'
                  : 'Results are posted to your main chat.'}
              </AppText>
            ) : null}
          </View>
        }>
        {DELIVERY_OPTIONS.map((option) => {
          const isAvailable =
            deliveries === null ? option.value === 'chat' : deliveries.has(option.value);
          const selected = values.delivery === option.value;
          return (
            <ListRow
              key={option.value}
              title={option.label}
              accessory={selected ? 'check' : 'none'}
              disabled={!isAvailable && !selected}
              accessibilityLabel={selected ? `${option.label}, selected` : option.label}
              onPress={() => update({ delivery: option.value }, 'delivery', 'deliveryTarget')}
            />
          );
        })}
      </ListSection>

      {values.delivery !== 'chat' ? (
        <ListSection
          header={`Where in ${deliveryOption?.label} (optional)`}
          footer={errorFooter(errors.deliveryTarget)}>
          <FieldTextInput
            value={values.deliveryTarget}
            onChangeText={(deliveryTarget) => update({ deliveryTarget }, 'deliveryTarget')}
            placeholder={deliveryOption?.targetHint}
            maxLength={DELIVERY_TARGET_MAX_LENGTH}
            autoCapitalize="none"
            autoCorrect={false}
            accessibilityLabel={`Where in ${deliveryOption?.label}`}
          />
        </ListSection>
      ) : null}
    </BottomSheet>
  );
};

function FieldError({ message }: { message?: string }) {
  return message ? (
    <AppText variant="footnote" color="destructive">
      {message}
    </AppText>
  ) : null;
}

/** A section's footer showing a field's error, or none. */
function errorFooter(message?: string) {
  return message ? <FieldError message={message} /> : undefined;
}

/** A form row with a value and an iOS stepper (− | +) at the right. */
function StepperRow({
  label,
  value,
  min,
  max,
  format,
  onChange,
  accessibilityLabel,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
  accessibilityLabel: string;
}) {
  const step = (next: number) => {
    haptic.selection();
    onChange(Math.min(max, Math.max(min, next)));
  };
  return (
    <View style={styles.stepperRow}>
      <AppText variant="body" style={styles.stepperLabel} numberOfLines={1}>
        {label}
      </AppText>
      <AppText variant="body" color="secondary" numberOfLines={1}>
        {format(value)}
      </AppText>
      <View
        style={[styles.stepper, continuous]}
        accessibilityLabel={`${accessibilityLabel}: ${format(value)}`}>
        <Pressable
          style={({ pressed }) => [styles.stepperHalf, pressed && styles.stepperHalfPressed]}
          onPress={() => step(value - 1)}
          disabled={value <= min}
          hitSlop={{ top: 6, bottom: 6, left: 4 }}
          accessibilityRole="button"
          accessibilityLabel="Fewer"
          accessibilityState={{ disabled: value <= min }}>
          <HugeiconsIcon
            icon={MinusSignIcon}
            size={16}
            color={value <= min ? Colors.tertiaryLabel : Colors.label}
            strokeWidth={2.2}
          />
        </Pressable>
        <View style={styles.stepperDivider} />
        <Pressable
          style={({ pressed }) => [styles.stepperHalf, pressed && styles.stepperHalfPressed]}
          onPress={() => step(value + 1)}
          disabled={value >= max}
          hitSlop={{ top: 6, bottom: 6, right: 4 }}
          accessibilityRole="button"
          accessibilityLabel="More"
          accessibilityState={{ disabled: value >= max }}>
          <HugeiconsIcon
            icon={PlusSignIcon}
            size={16}
            color={value >= max ? Colors.tertiaryLabel : Colors.label}
            strokeWidth={2.2}
          />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingBottom: 12,
  },
  submitError: {
    marginHorizontal: 32,
    marginBottom: 14,
  },
  cell: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  chips: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  days: {
    flexDirection: 'row',
    gap: 6,
  },
  dayChipContainer: {
    flex: 1,
  },
  dayChip: {
    paddingHorizontal: 0,
  },
  footerLines: {
    gap: 4,
  },
  linkPressed: {
    opacity: 0.5,
  },
  stepperRow: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  stepperLabel: {
    flex: 1,
  },
  stepper: {
    height: 32,
    flexDirection: 'row',
    alignItems: 'center',
    borderRadius: Radius.sm,
    backgroundColor: Colors.tertiaryFill,
    overflow: 'hidden',
  },
  stepperHalf: {
    width: 46,
    height: 32,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepperHalfPressed: {
    backgroundColor: Colors.fill,
  },
  stepperDivider: {
    width: Hairline,
    height: 18,
    backgroundColor: Colors.separator,
  },
});

export default ScheduleFormModal;
