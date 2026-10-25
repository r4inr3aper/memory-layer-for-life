/**
 * Date and time fields for the schedule form.
 *
 * Each shows its value as a button and opens the platform's own picker: a dialog on
 * Android, a spinner below the field on iOS. The web has no native picker here, so it
 * gets a text field instead.
 */

import DateTimePicker, {
  DateTimePickerAndroid,
  type DateTimePickerEvent,
} from '@react-native-community/datetimepicker';
import React, { useState } from 'react';
import { Platform, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { Colors } from '@/constants/colors';
import { formatClockTime, formatDate } from '@/lib/formatSchedule';
import { localDateTime, normalizeTime, toIsoDate } from '@/lib/scheduleForm';

interface FieldProps {
  /** HH:MM for a time, YYYY-MM-DD for a date. */
  value: string;
  onChange: (value: string) => void;
  hasError?: boolean;
  accessibilityLabel: string;
}

/** Whether the device shows times on a 24-hour clock. */
function uses24HourClock(): boolean {
  return new Date(2020, 0, 1, 13).toLocaleTimeString([]).includes('13');
}

export function TimeField({ value, onChange, hasError, accessibilityLabel }: FieldProps) {
  const [isOpen, setIsOpen] = useState(false);
  const current = localDateTime('2020-01-01', value) ?? new Date(2020, 0, 1, 9, 0);
  const toTime = (date: Date) =>
    `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;

  if (Platform.OS === 'web') {
    return (
      <WebInput
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
    <View>
      <TouchableOpacity
        style={[styles.field, hasError && styles.fieldError]}
        onPress={open}
        activeOpacity={0.75}
        accessibilityRole="button"
        accessibilityLabel={`${accessibilityLabel}: ${formatClockTime(value)}`}>
        <Text style={styles.fieldText}>{formatClockTime(value)}</Text>
      </TouchableOpacity>
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
    </View>
  );
}

export function DateField({ value, onChange, hasError, accessibilityLabel }: FieldProps) {
  const [isOpen, setIsOpen] = useState(false);
  const current = localDateTime(value, '12:00') ?? new Date();
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  if (Platform.OS === 'web') {
    return (
      <WebInput
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
    <View>
      <TouchableOpacity
        style={[styles.field, hasError && styles.fieldError]}
        onPress={open}
        activeOpacity={0.75}
        accessibilityRole="button"
        accessibilityLabel={`${accessibilityLabel}: ${formatDate(value)}`}>
        <Text style={styles.fieldText}>{formatDate(value)}</Text>
      </TouchableOpacity>
      {Platform.OS === 'ios' && isOpen ? (
        <DateTimePicker
          value={current}
          mode="date"
          display="inline"
          minimumDate={today}
          onChange={(_event: DateTimePickerEvent, selected?: Date) => {
            if (selected) onChange(toIsoDate(selected));
          }}
        />
      ) : null}
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
}: {
  value: string;
  parse: (text: string) => string | null;
  onChange: (value: string) => void;
  placeholder: string;
  maxLength: number;
  hasError?: boolean;
  accessibilityLabel: string;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <TextInput
      style={[styles.field, styles.webInput, hasError && styles.fieldError]}
      value={draft}
      onChangeText={setDraft}
      onBlur={() => {
        const parsed = parse(draft);
        if (parsed) onChange(parsed);
        else setDraft(value);
      }}
      placeholder={placeholder}
      placeholderTextColor={Colors.iconMuted}
      maxLength={maxLength}
      accessibilityLabel={accessibilityLabel}
    />
  );
}

const styles = StyleSheet.create({
  field: {
    alignSelf: 'flex-start',
    minWidth: 120,
    backgroundColor: Colors.surfaceInput,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: Colors.inputBarBorder,
  },
  fieldError: {
    borderColor: Colors.error,
  },
  fieldText: {
    fontSize: 15,
    fontWeight: '600',
    color: Colors.iconDark,
  },
  webInput: {
    fontSize: 15,
    fontWeight: '500',
    color: Colors.iconDark,
  },
});
