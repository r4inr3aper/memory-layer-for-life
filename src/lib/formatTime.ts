/**
 * Time Display Formatting
 */

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * Short relative time: "Just now", "5m ago", "3h ago", "Yesterday", "Mon", or "Oct 3".
 * Returns `fallback` for a missing or invalid date.
 */
export function formatRelativeTime(
  value: string | null | undefined,
  now: Date = new Date(),
  fallback = ''
): string {
  if (!value) {
    return fallback;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return fallback;
  }

  const elapsed = now.getTime() - date.getTime();
  if (elapsed < MINUTE_MS) {
    return 'Just now';
  }
  if (elapsed < HOUR_MS) {
    return `${Math.floor(elapsed / MINUTE_MS)}m ago`;
  }
  if (elapsed < DAY_MS && date.getDate() === now.getDate()) {
    return `${Math.floor(elapsed / HOUR_MS)}h ago`;
  }

  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (date.getTime() >= startOfToday - DAY_MS) {
    return 'Yesterday';
  }
  if (date.getTime() >= startOfToday - 6 * DAY_MS) {
    return date.toLocaleDateString([], { weekday: 'short' });
  }

  const sameYear = date.getFullYear() === now.getFullYear();
  return date.toLocaleDateString([], {
    month: 'short',
    day: 'numeric',
    ...(sameYear ? {} : { year: 'numeric' }),
  });
}

/**
 * When the daily prompts reset, in the user's own time: "at 5:30 AM" when that is still
 * today, "tomorrow at 5:30 AM" otherwise. Empty for an invalid date.
 */
export function formatResetTime(value: string, now: Date = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  return sameDay ? `at ${time}` : `tomorrow at ${time}`;
}
