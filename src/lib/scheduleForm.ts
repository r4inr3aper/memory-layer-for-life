/**
 * Schedule Form Rules
 *
 * The schedule form (new and edit) as plain values, checked with the same limits the
 * backend enforces so mistakes show next to the field, and turned into a request body
 * that carries only the rule fields its frequency uses.
 */

import type {
  CreateScheduleBody,
  Schedule,
  ScheduleDelivery,
  ScheduleFrequency,
  ScheduleRuleBody,
  Tool,
  UpdateScheduleBody,
  Weekday,
} from '@/lib/api/types';
import { WEEKDAY_ORDER, deviceTimezone, ruleWeekdays } from '@/lib/formatSchedule';

export const SCHEDULE_TITLE_MAX_LENGTH = 120;
export const SCHEDULE_TASK_MAX_LENGTH = 2000;
export const DELIVERY_TARGET_MAX_LENGTH = 200;
export const MIN_INTERVAL_HOURS = 1;
export const MAX_INTERVAL_HOURS = 24;

export const FREQUENCY_OPTIONS: readonly { value: ScheduleFrequency; label: string }[] = [
  { value: 'once', label: 'Once' },
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
  { value: 'monthly', label: 'Monthly' },
  { value: 'interval', label: 'Every few hours' },
];

export const WEEKDAYS: readonly { value: Weekday; label: string }[] = WEEKDAY_ORDER.map((day) => ({
  value: day,
  label: day.charAt(0).toUpperCase() + day.slice(1, 3),
}));

export const WEEKDAY_PRESETS: readonly { label: string; days: readonly Weekday[] }[] = [
  { label: 'Weekdays', days: WEEKDAY_ORDER.slice(0, 5) },
  { label: 'Weekends', days: ['saturday', 'sunday'] },
  { label: 'Every day', days: WEEKDAY_ORDER },
];

export const DELIVERY_OPTIONS: readonly {
  value: ScheduleDelivery;
  label: string;
  /** Example target, shown as the placeholder. */
  targetHint: string;
}[] = [
  { value: 'chat', label: 'Chat', targetHint: '' },
  { value: 'slack', label: 'Slack', targetHint: '#channel or @person' },
  { value: 'email', label: 'Email', targetHint: 'name@example.com' },
  { value: 'calendar', label: 'Calendar', targetHint: 'Calendar name' },
  { value: 'notion', label: 'Notion', targetHint: 'Page or database name' },
  { value: 'teams', label: 'Teams', targetHint: 'Team or channel' },
  { value: 'discord', label: 'Discord', targetHint: '#channel' },
];

/** The connected app that carries each delivery, as the backend maps them. */
export const DELIVERY_APPS: Readonly<Record<Exclude<ScheduleDelivery, 'chat'>, string>> = {
  slack: 'slack',
  email: 'gmail',
  calendar: 'googlecalendar',
  notion: 'notion',
  teams: 'microsoftteams',
  discord: 'discord',
};

/** Where results can go: chat, and each delivery whose app is connected. */
export function availableDeliveries(tools: readonly Tool[]): Set<ScheduleDelivery> {
  const connected = new Set(
    tools.filter((tool) => tool.status === 'connected').map((tool) => tool.slug)
  );
  const available = new Set<ScheduleDelivery>(['chat']);
  for (const [delivery, app] of Object.entries(DELIVERY_APPS)) {
    if (connected.has(app)) available.add(delivery as ScheduleDelivery);
  }
  return available;
}

export interface ScheduleFormValues {
  title: string;
  task: string;
  frequency: ScheduleFrequency;
  /** HH:MM, 24-hour. */
  time: string;
  /** YYYY-MM-DD, for a one-time schedule. */
  date: string;
  weekdays: Weekday[];
  dayOfMonth: number;
  intervalHours: number;
  delivery: ScheduleDelivery;
  deliveryTarget: string;
}

export type ScheduleFormField =
  | 'title'
  | 'task'
  | 'time'
  | 'date'
  | 'weekdays'
  | 'dayOfMonth'
  | 'intervalHours'
  | 'delivery'
  | 'deliveryTarget';

export type ScheduleFormErrors = Partial<Record<ScheduleFormField, string>>;

export type ScheduleFormResult<Body> =
  { ok: true; body: Body } | { ok: false; errors: ScheduleFormErrors };

export interface ScheduleFormContext {
  /** The schedule's timezone. */
  timezone: string;
  /** Deliveries the user can choose; others are refused. Omit to allow every one. */
  deliveries?: ReadonlySet<ScheduleDelivery>;
  /** For tests; defaults to the device clock. */
  now?: Date;
}

/** Defaults for a new schedule: daily at 09:00, a one-time date of tomorrow. */
export function newScheduleValues(now: Date = new Date()): ScheduleFormValues {
  return {
    title: '',
    task: '',
    frequency: 'daily',
    time: '09:00',
    date: toIsoDate(addDays(now, 1)),
    weekdays: WEEKDAY_ORDER.slice(0, 5),
    dayOfMonth: now.getDate(),
    intervalHours: 3,
    delivery: 'chat',
    deliveryTarget: '',
  };
}

/** The form filled in from a schedule, for editing. Unused fields keep useful defaults. */
export function scheduleToValues(schedule: Schedule, now: Date = new Date()): ScheduleFormValues {
  const defaults = newScheduleValues(now);
  const weekdays = ruleWeekdays(schedule);
  return {
    title: schedule.title,
    task: schedule.task,
    frequency: schedule.frequency,
    time: schedule.local_time,
    date:
      schedule.frequency === 'once' && schedule.start_date ? schedule.start_date : defaults.date,
    weekdays: weekdays.length ? weekdays : defaults.weekdays,
    dayOfMonth: schedule.day_of_month ?? defaults.dayOfMonth,
    intervalHours: schedule.interval_hours ?? defaults.intervalHours,
    delivery: schedule.delivery,
    deliveryTarget: schedule.delivery_target ?? '',
  };
}

/** Checks every field and builds the body to create a schedule. */
export function validateScheduleForm(
  values: ScheduleFormValues,
  context: ScheduleFormContext
): ScheduleFormResult<CreateScheduleBody> {
  const checked = check(values, context);
  if (!checked.ok) return checked;
  const { title, task, rule, target } = checked.body;
  return {
    ok: true,
    body: {
      title,
      task,
      ...rule,
      delivery: values.delivery,
      delivery_target: target,
    },
  };
}

/**
 * Checks every field and builds the body to edit `schedule`. The whole rule is sent, so it
 * replaces the old one; an interval keeps its first day unless its frequency changed.
 */
export function validateScheduleEdit(
  values: ScheduleFormValues,
  schedule: Schedule,
  context: ScheduleFormContext
): ScheduleFormResult<UpdateScheduleBody> {
  const checked = check(values, context);
  if (!checked.ok) return checked;
  const { title, task, rule, target } = checked.body;
  if (rule.frequency === 'interval' && schedule.frequency === 'interval') {
    rule.start_date = schedule.start_date;
  }
  return {
    ok: true,
    body: { title, task, ...rule, delivery: values.delivery, delivery_target: target },
  };
}

/**
 * A 24-hour time as `HH:MM`, accepting "8:05", "08:05", "0805", or "8.05".
 * Returns `null` when it is not a valid time.
 */
export function normalizeTime(input: string): string | null {
  const match = /^\s*(\d{1,2})[:.]?(\d{2})\s*$/.exec(input);
  if (!match) {
    return null;
  }
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) {
    return null;
  }
  return `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}

/** YYYY-MM-DD for a date in the device's calendar. */
export function toIsoDate(date: Date): string {
  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-');
}

/** A local Date for YYYY-MM-DD and HH:MM, or null when either is not valid. */
export function localDateTime(isoDate: string, time: string): Date | null {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  const normalized = normalizeTime(time);
  if (!dateMatch || !normalized) return null;
  const [year, month, day] = dateMatch.slice(1).map(Number);
  const [hour, minute] = normalized.split(':').map(Number);
  const date = new Date(year, month - 1, day, hour, minute);
  // new Date rolls 31 February over to March; such a date is not real.
  return date.getMonth() === month - 1 && date.getDate() === day ? date : null;
}

interface CheckedForm {
  title: string;
  task: string;
  rule: ScheduleRuleBody;
  target: string | null;
}

function check(
  values: ScheduleFormValues,
  { timezone, deliveries, now = new Date() }: ScheduleFormContext
): ScheduleFormResult<CheckedForm> {
  const errors: ScheduleFormErrors = {};
  const title = values.title.trim();
  const task = values.task.trim();
  const localTime = normalizeTime(values.time);
  const target = values.deliveryTarget.trim();

  if (!title) {
    errors.title = 'Give the schedule a title.';
  } else if (title.length > SCHEDULE_TITLE_MAX_LENGTH) {
    errors.title = `Keep the title under ${SCHEDULE_TITLE_MAX_LENGTH} characters.`;
  }

  if (!task) {
    errors.task = 'Describe what to do on each run.';
  } else if (task.length > SCHEDULE_TASK_MAX_LENGTH) {
    errors.task = `Keep the task under ${SCHEDULE_TASK_MAX_LENGTH} characters.`;
  }

  if (!localTime) {
    errors.time = 'Pick a time.';
  }

  const rule: ScheduleRuleBody = {
    frequency: values.frequency,
    local_time: localTime ?? '',
    timezone,
  };
  switch (values.frequency) {
    case 'once': {
      const at = localDateTime(values.date, values.time);
      if (!at) {
        errors.date = 'Pick a date.';
      } else if (timezone === deviceTimezone() && at.getTime() <= now.getTime()) {
        // Another timezone's "now" is the backend's to judge.
        errors.date = 'Pick a time in the future.';
      }
      rule.start_date = values.date;
      break;
    }
    case 'weekly':
      if (values.weekdays.length === 0) {
        errors.weekdays = 'Pick at least one day.';
      }
      rule.weekdays = WEEKDAY_ORDER.filter((day) => values.weekdays.includes(day));
      break;
    case 'monthly':
      if (!Number.isInteger(values.dayOfMonth) || values.dayOfMonth < 1 || values.dayOfMonth > 31) {
        errors.dayOfMonth = 'Pick a day from 1 to 31.';
      }
      rule.day_of_month = values.dayOfMonth;
      break;
    case 'interval':
      if (
        !Number.isInteger(values.intervalHours) ||
        values.intervalHours < MIN_INTERVAL_HOURS ||
        values.intervalHours > MAX_INTERVAL_HOURS
      ) {
        errors.intervalHours = `Pick ${MIN_INTERVAL_HOURS} to ${MAX_INTERVAL_HOURS} hours.`;
      }
      rule.interval_hours = values.intervalHours;
      break;
    default:
      break;
  }

  if (deliveries && !deliveries.has(values.delivery)) {
    const label = DELIVERY_OPTIONS.find((option) => option.value === values.delivery)?.label;
    errors.delivery = `Connect ${label ?? 'that app'} in Tools & Connections first.`;
  }
  if (values.delivery !== 'chat' && target.length > DELIVERY_TARGET_MAX_LENGTH) {
    errors.deliveryTarget = `Keep this under ${DELIVERY_TARGET_MAX_LENGTH} characters.`;
  }

  if (Object.keys(errors).length > 0) {
    return { ok: false, errors };
  }
  return {
    ok: true,
    body: { title, task, rule, target: values.delivery !== 'chat' && target ? target : null },
  };
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setDate(next.getDate() + days);
  return next;
}
