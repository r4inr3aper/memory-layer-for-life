import { formatRelativeTime, formatResetTime } from '@/lib/formatTime';

describe('formatRelativeTime', () => {
  // A Monday afternoon, local time.
  const now = new Date(2026, 9, 19, 15, 0, 0);
  const ago = (ms: number) => new Date(now.getTime() - ms).toISOString();
  const MINUTE = 60 * 1000;
  const HOUR = 60 * MINUTE;

  it('uses minutes and hours for today', () => {
    expect(formatRelativeTime(ago(20 * 1000), now)).toBe('Just now');
    expect(formatRelativeTime(ago(5 * MINUTE), now)).toBe('5m ago');
    expect(formatRelativeTime(ago(3 * HOUR), now)).toBe('3h ago');
  });

  it('says Yesterday, then the weekday, then the date', () => {
    expect(formatRelativeTime(new Date(2026, 9, 18, 23, 0).toISOString(), now)).toBe('Yesterday');

    const threeDaysAgo = new Date(2026, 9, 16, 9, 0);
    expect(formatRelativeTime(threeDaysAgo.toISOString(), now)).toBe(
      threeDaysAgo.toLocaleDateString([], { weekday: 'short' })
    );

    const lastMonth = new Date(2026, 8, 3, 9, 0);
    expect(formatRelativeTime(lastMonth.toISOString(), now)).toBe(
      lastMonth.toLocaleDateString([], { month: 'short', day: 'numeric' })
    );
  });

  it('returns the fallback for missing or invalid dates', () => {
    expect(formatRelativeTime(null, now, 'Recently')).toBe('Recently');
    expect(formatRelativeTime('not a date', now, 'Recently')).toBe('Recently');
  });
});

describe('formatResetTime', () => {
  const now = new Date(2026, 9, 19, 15, 0, 0);
  const timeOf = (date: Date) => date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  it('gives the time alone when the reset is later today', () => {
    const reset = new Date(2026, 9, 19, 17, 30);
    expect(formatResetTime(reset.toISOString(), now)).toBe(`at ${timeOf(reset)}`);
  });

  it('says tomorrow when the reset is after midnight', () => {
    const reset = new Date(2026, 9, 20, 5, 30);
    expect(formatResetTime(reset.toISOString(), now)).toBe(`tomorrow at ${timeOf(reset)}`);
  });

  it('is empty for an invalid date', () => {
    expect(formatResetTime('not a date', now)).toBe('');
  });
});
