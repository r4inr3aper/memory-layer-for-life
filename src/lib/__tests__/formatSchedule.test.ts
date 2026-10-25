import {
  formatDate,
  formatDayOfMonth,
  formatLocalDateTime,
  formatScheduleRule,
  formatTimezone,
  formatWeekdays,
  ruleWeekdays,
} from '@/lib/formatSchedule';

/** The time as the device formats it, so the test does not depend on the locale. */
function localTime(hour: number, minute: number): string {
  return new Date(2026, 0, 1, hour, minute).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  });
}

function localDate(year: number, month: number, day: number): string {
  return new Date(year, month - 1, day).toLocaleDateString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });
}

describe('formatScheduleRule', () => {
  it('describes a daily schedule', () => {
    expect(formatScheduleRule({ frequency: 'daily', local_time: '08:00' })).toBe(
      `Every day at ${localTime(8, 0)}`
    );
  });

  it('describes a one-time schedule with its date', () => {
    expect(
      formatScheduleRule({ frequency: 'once', local_time: '07:30', start_date: '2026-10-03' })
    ).toBe(`Once on ${localDate(2026, 10, 3)} at ${localTime(7, 30)}`);
  });

  it('describes weekly schedules by their days', () => {
    const at = localTime(9, 0);
    const weekly = (weekdays: Parameters<typeof formatWeekdays>[0]) =>
      formatScheduleRule({ frequency: 'weekly', local_time: '09:00', weekdays: [...weekdays] });

    expect(weekly(['monday'])).toBe(`Every Monday at ${at}`);
    expect(weekly(['friday', 'monday', 'wednesday'])).toBe(`Every Mon, Wed and Fri at ${at}`);
    expect(weekly(['monday', 'tuesday', 'wednesday', 'thursday', 'friday'])).toBe(
      `Weekdays at ${at}`
    );
    expect(weekly(['sunday', 'saturday'])).toBe(`Weekends at ${at}`);
  });

  it('reads a proposal made before weekdays became a list', () => {
    expect(
      formatScheduleRule({ frequency: 'weekly', local_time: '17:30', weekday: 'monday' })
    ).toBe(`Every Monday at ${localTime(17, 30)}`);
  });

  it('describes monthly and interval schedules', () => {
    expect(formatScheduleRule({ frequency: 'monthly', local_time: '09:00', day_of_month: 2 })).toBe(
      `Monthly on the 2nd at ${localTime(9, 0)}`
    );
    expect(
      formatScheduleRule({ frequency: 'interval', local_time: '09:00', interval_hours: 3 })
    ).toBe(`Every 3 hours from ${localTime(9, 0)}`);
    expect(
      formatScheduleRule({ frequency: 'interval', local_time: '09:00', interval_hours: 1 })
    ).toBe(`Every hour from ${localTime(9, 0)}`);
  });

  it('reports a pending schedule when the time is missing', () => {
    expect(formatScheduleRule({ frequency: 'daily', local_time: '' })).toBe('Schedule pending');
  });
});

describe('formatDayOfMonth', () => {
  it.each([
    [1, 'the 1st'],
    [2, 'the 2nd'],
    [3, 'the 3rd'],
    [11, 'the 11th'],
    [12, 'the 12th'],
    [13, 'the 13th'],
    [21, 'the 21st'],
    [22, 'the 22nd'],
    [23, 'the 23rd'],
    [30, 'the 30th'],
    [31, 'the last day'],
  ])('names day %p as %p', (day, expected) => {
    expect(formatDayOfMonth(day)).toBe(expected);
  });
});

describe('formatWeekdays', () => {
  it('names every day and no day', () => {
    expect(
      formatWeekdays(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
    ).toBe('Every day');
    expect(formatWeekdays([])).toBe('Every week');
  });
});

describe('ruleWeekdays', () => {
  it('orders the days and accepts the older single day', () => {
    expect(ruleWeekdays({ weekdays: ['friday', 'monday'] })).toEqual(['monday', 'friday']);
    expect(ruleWeekdays({ weekday: 'sunday' })).toEqual(['sunday']);
    expect(ruleWeekdays({})).toEqual([]);
  });
});

describe('formatTimezone', () => {
  it.each([
    ['Asia/Kolkata', 'Kolkata'],
    ['America/New_York', 'New York'],
    ['America/Argentina/Buenos_Aires', 'Buenos Aires'],
    ['UTC', 'UTC'],
  ])('shortens %p to %p', (timezone, expected) => {
    expect(formatTimezone(timezone)).toBe(expected);
  });
});

describe('formatLocalDateTime', () => {
  it('shows a wall-clock time without converting its timezone', () => {
    expect(formatLocalDateTime('2026-10-03T07:30')).toBe(
      `${localDate(2026, 10, 3)}, ${localTime(7, 30)}`
    );
  });

  it('leaves a malformed date as it is', () => {
    expect(formatDate('soon')).toBe('soon');
  });
});
