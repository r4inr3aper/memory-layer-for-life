/**
 * Schedule Display Formatting
 *
 * Rules read in the schedule's own timezone: "Weekdays at 8:00 AM", "Once on Sat 3 Oct at
 * 7:30 AM", "Every 3 hours from 9:00 AM". The backend sends the next run as a wall-clock
 * time in that timezone (`next_run_local`), so nothing here converts between zones; dates
 * are built from their parts, never parsed as UTC.
 */

import type { ScheduleFrequency, Weekday } from '@/lib/api/types';

/** The rule fields shared by schedules and schedule proposals. */
export interface ScheduleRuleFields {
  frequency: ScheduleFrequency;
  /** HH:MM, 24-hour. */
  local_time: string;
  weekdays?: Weekday[] | null;
  /** Proposals made before weekdays became a list name one day. */
  weekday?: Weekday | null;
  day_of_month?: number | null;
  /** YYYY-MM-DD. */
  start_date?: string | null;
  interval_hours?: number | null;
}

export const WEEKDAY_ORDER: readonly Weekday[] = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
];

const MONDAY_TO_FRIDAY: readonly Weekday[] = WEEKDAY_ORDER.slice(0, 5);
const WEEKEND: readonly Weekday[] = ['saturday', 'sunday'];

/** The days of a weekly rule, in order, from either form. */
export function ruleWeekdays(rule: Pick<ScheduleRuleFields, 'weekdays' | 'weekday'>): Weekday[] {
  const days = rule.weekdays?.length ? rule.weekdays : rule.weekday ? [rule.weekday] : [];
  return WEEKDAY_ORDER.filter((day) => days.includes(day));
}

export function formatScheduleRule(rule: ScheduleRuleFields): string {
  if (!rule?.local_time) {
    return 'Schedule pending';
  }
  const at = formatClockTime(rule.local_time);

  switch (rule.frequency) {
    case 'once':
      return rule.start_date ? `Once on ${formatDate(rule.start_date)} at ${at}` : `Once at ${at}`;
    case 'weekly':
      return `${formatWeekdays(ruleWeekdays(rule))} at ${at}`;
    case 'monthly':
      return `Monthly on ${formatDayOfMonth(rule.day_of_month)} at ${at}`;
    case 'interval': {
      const hours = rule.interval_hours ?? 1;
      return `${hours === 1 ? 'Every hour' : `Every ${hours} hours`} from ${at}`;
    }
    default:
      return `Every day at ${at}`;
  }
}

/** "Weekdays", "Weekends", "Every day", "Every Monday", or "Every Mon, Wed and Fri". */
export function formatWeekdays(days: readonly Weekday[]): string {
  const sorted = WEEKDAY_ORDER.filter((day) => days.includes(day));
  if (sorted.length === 0) return 'Every week';
  if (sorted.length === 7) return 'Every day';
  if (sameDays(sorted, MONDAY_TO_FRIDAY)) return 'Weekdays';
  if (sameDays(sorted, WEEKEND)) return 'Weekends';
  if (sorted.length === 1) return `Every ${capitalize(sorted[0])}`;
  const short = sorted.map((day) => capitalize(day.slice(0, 3)));
  return `Every ${short.slice(0, -1).join(', ')} and ${short[short.length - 1]}`;
}

/** "the 1st", "the 22nd", or "the last day" for 31, which a shorter month moves to its end. */
export function formatDayOfMonth(day: number | null | undefined): string {
  if (!day) return 'a day of the month';
  if (day === 31) return 'the last day';
  return `the ${ordinal(day)}`;
}

/** "Kolkata" for Asia/Kolkata, "New York" for America/New_York, and "UTC" as is. */
export function formatTimezone(timezone: string): string {
  const city = timezone.split('/').pop() ?? timezone;
  return city.replace(/_/g, ' ');
}

/** "Sat 3 Oct, 7:30 AM" for a wall-clock time sent as YYYY-MM-DDTHH:MM. */
export function formatLocalDateTime(local: string): string {
  const [day, time] = local.split('T');
  return time ? `${formatDate(day)}, ${formatClockTime(time)}` : formatDate(day);
}

/** "Sat 3 Oct" for YYYY-MM-DD, without a timezone shift. */
export function formatDate(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  if (!year || !month || !day) return isoDate;
  return new Date(year, month - 1, day).toLocaleDateString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

/** An HH:MM time in the device's 12- or 24-hour style. */
export function formatClockTime(time: string): string {
  const [hour, minute] = time.split(':').map(Number);
  const date = new Date();
  date.setHours(hour, minute, 0, 0);
  return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
}

/** The device's IANA timezone, or UTC when it cannot tell. */
export function deviceTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** 1st, 2nd, 3rd, 4th, 11th, 21st, 31st. */
export function ordinal(day: number): string {
  const lastTwo = day % 100;
  if (lastTwo >= 11 && lastTwo <= 13) return `${day}th`;
  const suffix = { 1: 'st', 2: 'nd', 3: 'rd' }[day % 10] ?? 'th';
  return `${day}${suffix}`;
}

function sameDays(a: readonly Weekday[], b: readonly Weekday[]): boolean {
  return a.length === b.length && a.every((day) => b.includes(day));
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
