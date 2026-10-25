/**
 * Life State Helpers
 *
 * Dates for to-dos and reminders: labels ("Today", "Tomorrow", "Sat 3 Oct"), quick choices
 * for a due date or a snooze, and the conversions between the phone's calendar and the
 * API's `YYYY-MM-DD` dates and ISO times. Pure, so the wording and the arithmetic are
 * tested.
 */

const DAY_MS = 24 * 60 * 60 * 1000;

/** `YYYY-MM-DD` of a moment in the phone's timezone. */
export function isoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${date.getFullYear()}-${month}-${day}`;
}

/** The local midnight starting a `YYYY-MM-DD` date. */
export function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export function addDays(value: string, days: number): string {
  const date = parseIsoDate(value);
  date.setDate(date.getDate() + days);
  return isoDate(date);
}

/** Whole days from `from` to `to`, both `YYYY-MM-DD`. */
export function daysBetween(from: string, to: string): number {
  return Math.round((parseIsoDate(to).getTime() - parseIsoDate(from).getTime()) / DAY_MS);
}

function shortDate(value: string): string {
  return parseIsoDate(value).toLocaleDateString(undefined, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

/** "Today", "Tomorrow", "Yesterday", a weekday within the week, else "Sat, 3 Oct". */
export function dueLabel(dueOn: string, today: string): string {
  const days = daysBetween(today, dueOn);
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  if (days === -1) return 'Yesterday';
  if (days > 1 && days < 7) {
    return parseIsoDate(dueOn).toLocaleDateString(undefined, { weekday: 'long' });
  }
  return shortDate(dueOn);
}

function clock(date: Date): string {
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

/** When a reminder goes off: "Today 18:00", "Tomorrow 09:00", or "Sat, 3 Oct 09:00". */
export function reminderLabel(remindAt: string, now: Date = new Date()): string {
  const moment = new Date(remindAt);
  const day = dueLabel(isoDate(moment), isoDate(now));
  return `${day} ${clock(moment)}`;
}

export interface Choice {
  label: string;
  value: string;
}

/** Quick due dates: today, tomorrow, the coming Saturday, and next Monday. */
export function dueChoices(today: string): Choice[] {
  const weekday = parseIsoDate(today).getDay(); // 0 is Sunday
  const toSaturday = (6 - weekday + 7) % 7 || 7;
  const toMonday = (1 - weekday + 7) % 7 || 7;
  return [
    { label: 'Today', value: today },
    { label: 'Tomorrow', value: addDays(today, 1) },
    { label: 'This weekend', value: addDays(today, toSaturday) },
    { label: 'Next week', value: addDays(today, toMonday) },
  ];
}

function at(date: Date, hours: number, minutes = 0): Date {
  const result = new Date(date);
  result.setHours(hours, minutes, 0, 0);
  return result;
}

/**
 * Quick snoozes as ISO times: in an hour, this evening at 18:00 (while it is before
 * 17:00), tomorrow at 09:00, and next Monday at 09:00.
 */
export function snoozeChoices(now: Date = new Date()): Choice[] {
  const choices: Choice[] = [
    { label: 'In 1 hour', value: new Date(now.getTime() + 60 * 60 * 1000).toISOString() },
  ];
  if (now.getHours() < 17) {
    choices.push({ label: 'This evening', value: at(now, 18).toISOString() });
  }
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  choices.push({ label: 'Tomorrow morning', value: at(tomorrow, 9).toISOString() });
  const monday = new Date(now);
  monday.setDate(now.getDate() + ((1 - now.getDay() + 7) % 7 || 7));
  choices.push({ label: 'Next Monday', value: at(monday, 9).toISOString() });
  return choices;
}

/** An ISO time for a local date (`YYYY-MM-DD`) and time (`HH:MM`). */
export function localIsoTime(date: string, time: string): string {
  const [hours, minutes] = time.split(':').map(Number);
  return at(parseIsoDate(date), hours, minutes).toISOString();
}

/** Splits a search snippet into plain and matched parts (matches are wrapped in << >>). */
export function snippetParts(snippet: string): { text: string; match: boolean }[] {
  const parts: { text: string; match: boolean }[] = [];
  const pattern = /<<(.*?)>>/g;
  let last = 0;
  for (const found of snippet.matchAll(pattern)) {
    const index = found.index ?? 0;
    if (index > last) parts.push({ text: snippet.slice(last, index), match: false });
    parts.push({ text: found[1], match: true });
    last = index + found[0].length;
  }
  if (last < snippet.length) parts.push({ text: snippet.slice(last), match: false });
  return parts;
}
