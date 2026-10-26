/**
 * Form controls for the to-do and schedule editors (TimeField also sets the brief time in
 * Settings).
 *
 * - `DateField` / `TimeField`: with a `label`, an iOS form row: the label at the left and
 *   the value in the tint at the right. Without one, a compact gray capsule holding the
 *   value, like iOS's compact date picker, to sit among other content. Either opens the
 *   platform's own picker: a dialog on Android, a picker below the field on iOS. The web
 *   has no native picker here, so it gets a text field instead.
 * - `FieldTextInput`: a borderless text field for a white cell of an inset-grouped list.
 * - `ChoiceChip`: a capsule for picking among a few options, tinted when selected.
 */

import DateTimePicker, {
  DateTimePickerAndroid,
  type DateTimePickerEvent,
} from '@react-native-community/datetimepicker';
import React, { useState } from 'react';
import {
  Platform,
  StyleSheet,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import { AppText } from '@/components/ui/AppText';
import { ListRow } from '@/components/ui/List';
import { PressableScale } from '@/components/ui/PressableScale';
import { Colors } from '@/constants/colors';
import { Radius, Typography, continuous } from '@/constants/theme';
import { formatClockTime, formatDate } from '@/lib/formatSchedule';
import { haptic } from '@/lib/haptics';
import { localDateTime, normalizeTime, toIsoDate } from '@/lib/scheduleForm';

interface FieldProps {
  /** HH:MM for a time, YYYY-MM-DD for a date. */
  value: string;
  onChange: (value: string) => void;
  hasError?: boolean;
  accessibilityLabel: string;
  /** Shows the field as a form row with this title; without it, a compact capsule. */
  label?: string;
}

/** Whether the device shows times on a 24-hour clock. */
function uses24HourClock(): boolean {
  return new Date(2020, 0, 1, 13).toLocaleTimeString([]).includes('13');
}

export function TimeField({ value, onChange, hasError, accessibilityLabel, label }: FieldProps) {
  const [isOpen, setIsOpen] = useState(false);
  const current = localDateTime('2020-01-01', value) ?? new Date(2020, 0, 1, 9, 0);
  const toTime = (date: Date) =>
    `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  const display = formatClockTime(value);

  if (Platform.OS === 'web') {
    return (
      <WebField
        label={label}
        value={value}
        parse={normalizeTime}
        onChange={onChange}
        placeholder="08:30"
        maxLength={5}
        hasError={hasError}
        accessibilityLabel={accessibilityLabel}
      />
    );
  }

  const open = () => {
    if (Platform.OS === 'android') {
      DateTimePickerAndroid.open({
        value: current,
        mode: 'time',
        is24Hour: uses24HourClock(),
        onChange: (event: DateTimePickerEvent, selected?: Date) => {
          if (event.type === 'set' && selected) onChange(toTime(selected));
        },
      });
    } else {
      setIsOpen((open) => !open);
    }
  };

  return (
    <FieldShell
      label={label}
      display={display}
      isOpen={isOpen}
      hasError={hasError}
      onPress={open}
      accessibilityLabel={`${accessibilityLabel}: ${display}`}>
      {Platform.OS === 'ios' && isOpen ? (
        <DateTimePicker
          value={current}
          mode="time"
          display="spinner"
          onChange={(_event: DateTimePickerEvent, selected?: Date) => {
            if (selected) onChange(toTime(selected));
          }}
        />
      ) : null}
    </FieldShell>
  );
}

export function DateField({ value, onChange, hasError, accessibilityLabel, label }: FieldProps) {
  const [isOpen, setIsOpen] = useState(false);
  const current = localDateTime(value, '12:00') ?? new Date();
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const display = formatDate(value);

  if (Platform.OS === 'web') {
    return (
      <WebField
        label={label}
        value={value}
        parse={(text) => (localDateTime(text, '12:00') ? text.trim() : null)}
        onChange={onChange}
        placeholder="2026-12-31"
        maxLength={10}
        hasError={hasError}
        accessibilityLabel={accessibilityLabel}
      />
    );
  }

  const open = () => {
    if (Platform.OS === 'android') {
      DateTimePickerAndroid.open({
        value: current,
        mode: 'date',
        minimumDate: today,
        onChange: (event: DateTimePickerEvent, selected?: Date) => {
          if (event.type === 'set' && selected) onChange(toIsoDate(selected));
        },
      });
    } else {
      setIsOpen((open) => !open);
    }
  };

  return (
    <FieldShell
      label={label}
      display={display}
      isOpen={isOpen}
      hasError={hasError}
      onPress={open}
      accessibilityLabel={`${accessibilityLabel}: ${display}`}>
      {Platform.OS === 'ios' && isOpen ? (
        <DateTimePicker
          value={current}
          mode="date"
          display="inline"
          minimumDate={today}
          accentColor={Colors.tint}
          onChange={(_event: DateTimePickerEvent, selected?: Date) => {
            if (selected) onChange(toIsoDate(selected));
          }}
        />
      ) : null}
    </FieldShell>
  );
}

/** The visible part of a date or time field: a form row, or a compact capsule. */
function FieldShell({
  label,
  display,
  isOpen,
  hasError,
  onPress,
  accessibilityLabel,
  children,
}: {
  label?: string;
  display: string;
  isOpen: boolean;
  hasError?: boolean;
  onPress: () => void;
  accessibilityLabel: string;
  /** The iOS picker, shown under the field while it is open. */
  children: React.ReactNode;
}) {
  if (label) {
    return (
      <View>
        <ListRow
          title={label}
          accessory={
            <AppText variant="body" color={hasError ? 'destructive' : 'tint'} numberOfLines={1}>
              {display}
            </AppText>
          }
          onPress={onPress}
          accessibilityLabel={accessibilityLabel}
        />
        {children ? <View style={styles.rowPicker}>{children}</View> : null}
      </View>
    );
  }
  return (
    <View>
      <PressableScale
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={accessibilityLabel}
        containerStyle={styles.compactContainer}
        style={[styles.compact, continuous]}>
        <AppText
          variant="body"
          color={hasError ? 'destructive' : isOpen ? 'tint' : 'primary'}
          numberOfLines={1}>
          {display}
        </AppText>
      </PressableScale>
      {children}
    </View>
  );
}

/** The web's stand-in for a date or time field: a text field, in a row or alone. */
function WebField({
  label,
  ...input
}: {
  label?: string;
  value: string;
  parse: (text: string) => string | null;
  onChange: (value: string) => void;
  placeholder: string;
  maxLength: number;
  hasError?: boolean;
  accessibilityLabel: string;
}) {
  if (!label) {
    return <WebInput {...input} style={[styles.compact, styles.compactInput]} />;
  }
  return (
    <View style={styles.webRow}>
      <AppText variant="body" style={styles.webRowLabel} numberOfLines={1}>
        {label}
      </AppText>
      <WebInput {...input} style={styles.webRowInput} />
    </View>
  );
}

/** A text field that hands back its value once it parses, when it loses focus. */
function WebInput({
  value,
  parse,
  onChange,
  placeholder,
  maxLength,
  hasError,
  accessibilityLabel,
  style,
}: {
  value: string;
  parse: (text: string) => string | null;
  onChange: (value: string) => void;
  placeholder: string;
  maxLength: number;
  hasError?: boolean;
  accessibilityLabel: string;
  style?: StyleProp<TextStyle>;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <TextInput
      style={[styles.webInput, style, hasError && styles.webInputError]}
      value={draft}
      onChangeText={setDraft}
      onBlur={() => {
        const parsed = parse(draft);
        if (parsed) onChange(parsed);
        else setDraft(value);
      }}
      placeholder={placeholder}
      placeholderTextColor={Colors.placeholder}
      maxLength={maxLength}
      accessibilityLabel={accessibilityLabel}
    />
  );
}

/** A borderless text field filling a white cell of an inset-grouped list. */
export function FieldTextInput({ style, multiline, ...props }: TextInputProps) {
  return (
    <TextInput
      placeholderTextColor={Colors.placeholder}
      selectionColor={Colors.tint}
      cursorColor={Colors.tint}
      {...props}
      multiline={multiline}
      style={[styles.textInput, multiline && styles.textInputMultiline, style]}
    />
  );
}

/**
 * A capsule among a few options. Single choice by default: pressing the selected one does
 * nothing new, so it ticks only on a change. `multiSelect` chips toggle and tick each time.
 */
export function ChoiceChip({
  label,
  selected,
  disabled = false,
  multiSelect = false,
  onPress,
  style,
  containerStyle,
}: {
  label: string;
  selected: boolean;
  disabled?: boolean;
  multiSelect?: boolean;
  onPress: () => void;
  style?: StyleProp<ViewStyle>;
  containerStyle?: StyleProp<ViewStyle>;
}) {
  return (
    <PressableScale
      onPress={() => {
        if (multiSelect || !selected) haptic.selection();
        onPress();
      }}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityState={{ selected, disabled }}
      containerStyle={containerStyle}
      style={[styles.chip, continuous, selected && styles.chipSelected, style]}>
      <AppText
        variant="subheadline"
        weight={selected ? '600' : '400'}
        color={selected ? 'tint' : 'primary'}
        numberOfLines={1}>
        {label}
      </AppText>
    </PressableScale>
  );
}

const styles = StyleSheet.create({
  rowPicker: {
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingBottom: 8,
  },
  compactContainer: {
    alignSelf: 'flex-start',
  },
  compact: {
    minHeight: 34,
    paddingHorizontal: 12,
    borderRadius: Radius.sm,
    backgroundColor: Colors.tertiaryFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  compactInput: {
    minWidth: 96,
    textAlign: 'center',
  },
  webRow: {
    minHeight: 48,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    paddingHorizontal: 16,
  },
  webRowLabel: {
    flex: 1,
  },
  webRowInput: {
    minWidth: 96,
    paddingVertical: 12,
    textAlign: 'right',
    color: Colors.tint,
  },
  webInput: {
    fontSize: Typography.body.fontSize,
    letterSpacing: Typography.body.letterSpacing,
    color: Colors.label,
  },
  webInputError: {
    color: Colors.systemRed,
  },
  textInput: {
    minHeight: 48,
    paddingHorizontal: 16,
    paddingVertical: 13,
    fontSize: Typography.body.fontSize,
    letterSpacing: Typography.body.letterSpacing,
    color: Colors.label,
  },
  textInputMultiline: {
    minHeight: 112,
    lineHeight: Typography.body.lineHeight,
    textAlignVertical: 'top',
  },
  chip: {
    height: 32,
    paddingHorizontal: 14,
    borderRadius: Radius.pill,
    backgroundColor: Colors.tertiaryFill,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chipSelected: {
    backgroundColor: Colors.tintFill,
  },
});
