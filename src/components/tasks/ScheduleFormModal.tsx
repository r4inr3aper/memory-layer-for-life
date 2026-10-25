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
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Modal,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  TouchableWithoutFeedback,
  View,
} from 'react-native';
import { useRouter } from 'expo-router';
import { HugeiconsIcon } from '@hugeicons/react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Cancel01Icon, MinusSignIcon, PlusSignIcon } from '@hugeicons/core-free-icons';
import { Colors } from '@/constants/colors';
import { showToast } from '@/context/ToastContext';
import { getErrorMessage, isAbortError } from '@/lib/api/client';
import { createSchedule, updateSchedule } from '@/lib/api/schedules';
import { listTools } from '@/lib/api/tools';
import type { Schedule, ScheduleDelivery, Weekday } from '@/lib/api/types';
import { deviceTimezone, formatTimezone, ordinal } from '@/lib/formatSchedule';
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
import { DateField, TimeField } from './DateTimeFields';

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
  // Modals are drawn edge-to-edge too: keep the sheet's last row above the navigation bar.
  const insets = useSafeAreaInsets();
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
              <Text style={styles.title}>{isEditing ? 'Edit schedule' : 'New schedule'}</Text>
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
              {/* Title */}
              <Text style={styles.label}>Title</Text>
              <TextInput
                style={[styles.input, errors.title && styles.inputError]}
                value={values.title}
                onChangeText={(title) => update({ title }, 'title')}
                placeholder="Morning inbox summary"
                placeholderTextColor={Colors.iconMuted}
                maxLength={SCHEDULE_TITLE_MAX_LENGTH}
                returnKeyType="next"
              />
              <FieldError message={errors.title} />

              {/* Task */}
              <Text style={styles.label}>Task</Text>
              <TextInput
                style={[styles.input, styles.multilineInput, errors.task && styles.inputError]}
                value={values.task}
                onChangeText={(task) => update({ task }, 'task')}
                placeholder="Summarize my unread emails and list anything that needs a reply."
                placeholderTextColor={Colors.iconMuted}
                maxLength={SCHEDULE_TASK_MAX_LENGTH}
                multiline
                textAlignVertical="top"
              />
              <FieldError message={errors.task} />

              {/* How often */}
              <Text style={styles.label}>Repeats</Text>
              <View style={styles.chipRow}>
                {FREQUENCY_OPTIONS.map((option) => (
                  <Chip
                    key={option.value}
                    label={option.label}
                    selected={values.frequency === option.value}
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
                ))}
              </View>

              {values.frequency === 'once' ? (
                <>
                  <Text style={styles.label}>Date</Text>
                  <DateField
                    value={values.date}
                    onChange={(date) => update({ date }, 'date')}
                    hasError={Boolean(errors.date)}
                    accessibilityLabel="Date"
                  />
                  <FieldError message={errors.date} />
                </>
              ) : null}

              {values.frequency === 'weekly' ? (
                <>
                  <Text style={styles.label}>Days</Text>
                  <View style={styles.chipRow}>
                    {WEEKDAY_PRESETS.map((preset) => (
                      <Chip
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
                  <View style={[styles.chipRow, styles.chipRowSpaced]}>
                    {WEEKDAYS.map((day) => (
                      <Chip
                        key={day.value}
                        label={day.label}
                        selected={values.weekdays.includes(day.value)}
                        onPress={() => toggleWeekday(day.value)}
                      />
                    ))}
                  </View>
                  <FieldError message={errors.weekdays} />
                </>
              ) : null}

              {values.frequency === 'monthly' ? (
                <>
                  <Text style={styles.label}>Day of the month</Text>
                  <Stepper
                    value={values.dayOfMonth}
                    min={1}
                    max={31}
                    format={(day) => String(day)}
                    onChange={(dayOfMonth) => update({ dayOfMonth }, 'dayOfMonth')}
                    accessibilityLabel="Day of the month"
                  />
                  {values.dayOfMonth >= 29 ? (
                    <Text style={styles.hintText}>
                      Months without a {ordinal(values.dayOfMonth)} run on their last day.
                    </Text>
                  ) : null}
                  <FieldError message={errors.dayOfMonth} />
                </>
              ) : null}

              {values.frequency === 'interval' ? (
                <>
                  <Text style={styles.label}>Every</Text>
                  <Stepper
                    value={values.intervalHours}
                    min={MIN_INTERVAL_HOURS}
                    max={MAX_INTERVAL_HOURS}
                    format={(hours) => (hours === 1 ? '1 hour' : `${hours} hours`)}
                    onChange={(intervalHours) => update({ intervalHours }, 'intervalHours')}
                    accessibilityLabel="Hours between runs"
                  />
                  <Text style={styles.hintText}>
                    About {runsPerDay} {runsPerDay === 1 ? 'run' : 'runs'} a day; each uses one of
                    your daily prompts.
                  </Text>
                  <FieldError message={errors.intervalHours} />
                </>
              ) : null}

              {/* Time */}
              <Text style={styles.label}>
                {values.frequency === 'interval' ? 'Starting at' : 'At'}
              </Text>
              <TimeField
                value={values.time}
                onChange={(time) => update({ time }, 'time', 'date')}
                hasError={Boolean(errors.time)}
                accessibilityLabel="Time"
              />
              <FieldError message={errors.time} />
              <Text style={styles.hintText}>
                Times are in {formatTimezone(timezone)} ({timezone}).
              </Text>
              {timezone !== phoneTimezone ? (
                <TouchableOpacity
                  onPress={() => setTimezone(phoneTimezone)}
                  activeOpacity={0.7}
                  accessibilityRole="button">
                  <Text style={styles.linkText}>
                    Use this phone&apos;s timezone ({formatTimezone(phoneTimezone)})
                  </Text>
                </TouchableOpacity>
              ) : null}

              {/* Delivery */}
              <Text style={styles.label}>Send results to</Text>
              <View style={styles.chipRow}>
                {DELIVERY_OPTIONS.map((option) => {
                  const isAvailable =
                    deliveries === null ? option.value === 'chat' : deliveries.has(option.value);
                  return (
                    <Chip
                      key={option.value}
                      label={option.label}
                      selected={values.delivery === option.value}
                      disabled={!isAvailable && values.delivery !== option.value}
                      onPress={() =>
                        update({ delivery: option.value }, 'delivery', 'deliveryTarget')
                      }
                    />
                  );
                })}
                {deliveries === null ? (
                  <ActivityIndicator size="small" color={Colors.iconMuted} />
                ) : null}
              </View>
              <FieldError message={errors.delivery} />
              <TouchableOpacity
                onPress={openConnections}
                activeOpacity={0.7}
                accessibilityRole="link">
                <Text style={styles.hintText}>
                  Only connected apps can receive results.{' '}
                  <Text style={styles.linkText}>Manage connections</Text>
                </Text>
              </TouchableOpacity>

              {values.delivery !== 'chat' ? (
                <>
                  <Text style={styles.label}>Where in {deliveryOption?.label} (optional)</Text>
                  <TextInput
                    style={[styles.input, errors.deliveryTarget && styles.inputError]}
                    value={values.deliveryTarget}
                    onChangeText={(deliveryTarget) => update({ deliveryTarget }, 'deliveryTarget')}
                    placeholder={deliveryOption?.targetHint}
                    placeholderTextColor={Colors.iconMuted}
                    maxLength={DELIVERY_TARGET_MAX_LENGTH}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  <FieldError message={errors.deliveryTarget} />
                </>
              ) : (
                <Text style={styles.hintText}>
                  {isEditing && schedule?.source_thread_id
                    ? 'Results are posted to the chat this schedule came from.'
                    : 'Results are posted to your main chat.'}
                </Text>
              )}

              {submitError ? (
                <View style={styles.submitErrorBox}>
                  <Text style={styles.submitErrorText}>{submitError}</Text>
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
                activeOpacity={0.8}>
                {isSaving ? (
                  <ActivityIndicator size="small" color={Colors.white} />
                ) : (
                  <Text style={styles.saveText}>{isEditing ? 'Save' : 'Create'}</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

function FieldError({ message }: { message?: string }) {
  return message ? <Text style={styles.errorText}>{message}</Text> : null;
}

function Chip({
  label,
  selected,
  disabled = false,
  onPress,
}: {
  label: string;
  selected: boolean;
  disabled?: boolean;
  onPress: () => void;
}) {
  return (
    <TouchableOpacity
      style={[styles.chip, selected && styles.chipSelected, disabled && styles.chipDisabled]}
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.75}
      accessibilityRole="button"
      accessibilityState={{ selected, disabled }}>
      <Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text>
    </TouchableOpacity>
  );
}

function Stepper({
  value,
  min,
  max,
  format,
  onChange,
  accessibilityLabel,
}: {
  value: number;
  min: number;
  max: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
  accessibilityLabel: string;
}) {
  return (
    <View style={styles.stepper} accessibilityLabel={`${accessibilityLabel}: ${format(value)}`}>
      <TouchableOpacity
        style={[styles.stepperBtn, value <= min && styles.stepperBtnDisabled]}
        onPress={() => onChange(Math.max(min, value - 1))}
        disabled={value <= min}
        accessibilityRole="button"
        accessibilityLabel="Fewer">
        <HugeiconsIcon icon={MinusSignIcon} size={16} color={Colors.iconDark} />
      </TouchableOpacity>
      <Text style={styles.stepperValue}>{format(value)}</Text>
      <TouchableOpacity
        style={[styles.stepperBtn, value >= max && styles.stepperBtnDisabled]}
        onPress={() => onChange(Math.min(max, value + 1))}
        disabled={value >= max}
        accessibilityRole="button"
        accessibilityLabel="More">
        <HugeiconsIcon icon={PlusSignIcon} size={16} color={Colors.iconDark} />
      </TouchableOpacity>
    </View>
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
  errorText: {
    marginTop: 6,
    fontSize: 12.5,
    color: Colors.error,
  },
  hintText: {
    marginTop: 6,
    fontSize: 12.5,
    lineHeight: 17,
    color: Colors.textSecondary,
  },
  linkText: {
    marginTop: 6,
    fontSize: 12.5,
    fontWeight: '600',
    color: Colors.primary,
  },
  chipRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 8,
  },
  chipRowSpaced: {
    marginTop: 8,
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
  chipDisabled: {
    opacity: 0.4,
  },
  chipText: {
    fontSize: 13,
    fontWeight: '600',
    color: Colors.textSecondary,
  },
  chipTextSelected: {
    color: Colors.primary,
  },
  stepper: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    gap: 12,
  },
  stepperBtn: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: Colors.avatarPreviewBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  stepperBtnDisabled: {
    opacity: 0.35,
  },
  stepperValue: {
    minWidth: 72,
    textAlign: 'center',
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

export default ScheduleFormModal;
