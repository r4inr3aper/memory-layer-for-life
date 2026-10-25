import type { Schedule, Tool } from '@/lib/api/types';
import { deviceTimezone } from '@/lib/formatSchedule';
import {
  availableDeliveries,
  localDateTime,
  newScheduleValues,
  normalizeTime,
  scheduleToValues,
  toIsoDate,
  validateScheduleEdit,
  validateScheduleForm,
  type ScheduleFormValues,
} from '@/lib/scheduleForm';

// Thursday 1 October 2026, 12:00 on the device's clock.
const NOW = new Date(2026, 9, 1, 12, 0);

const validValues: ScheduleFormValues = {
  ...newScheduleValues(NOW),
  title: '  Morning inbox  ',
  task: ' Summarize unread email ',
  time: '8:05',
  deliveryTarget: 'ignored for chat',
};

const UTC = { timezone: 'UTC', now: NOW };

function schedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    id: 'schedule-1',
    title: 'Plants',
    original_prompt: 'Remind me about the plants',
    task: 'Remind me to water the plants.',
    frequency: 'daily',
    local_time: '09:00',
    weekdays: [],
    day_of_month: null,
    start_date: null,
    interval_hours: null,
    timezone: 'Asia/Kolkata',
    delivery: 'chat',
    delivery_target: null,
    status: 'active',
    next_run_at: null,
    next_run_local: null,
    last_run_at: null,
    last_run_status: null,
    last_run_summary: null,
    last_run_error: null,
    run_count: 0,
    source_thread_id: null,
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

describe('normalizeTime', () => {
  it.each([
    ['08:05', '08:05'],
    ['8:05', '08:05'],
    ['0805', '08:05'],
    ['8.05', '08:05'],
    [' 23:59 ', '23:59'],
    ['0:00', '00:00'],
  ])('reads %p as %p', (input, expected) => {
    expect(normalizeTime(input)).toBe(expected);
  });

  it.each(['24:00', '12:60', '8', '8:5', 'noon', ''])('rejects %p', (input) => {
    expect(normalizeTime(input)).toBeNull();
  });
});

describe('dates', () => {
  it('writes a device date as YYYY-MM-DD', () => {
    expect(toIsoDate(new Date(2026, 0, 5))).toBe('2026-01-05');
  });

  it('reads a date and time on the device clock, refusing dates that do not exist', () => {
    expect(localDateTime('2026-10-03', '07:30')).toEqual(new Date(2026, 9, 3, 7, 30));
    expect(localDateTime('2026-02-30', '07:30')).toBeNull();
    expect(localDateTime('2026-10-03', 'noon')).toBeNull();
  });
});

describe('newScheduleValues', () => {
  it('starts daily at 09:00, with tomorrow for a one-time date and weekdays picked', () => {
    const values = newScheduleValues(NOW);

    expect(values.frequency).toBe('daily');
    expect(values.time).toBe('09:00');
    expect(values.date).toBe('2026-10-02');
    expect(values.weekdays).toEqual(['monday', 'tuesday', 'wednesday', 'thursday', 'friday']);
  });
});

describe('validateScheduleForm', () => {
  it('builds a daily request body with trimmed text and no rule extras or target', () => {
    expect(validateScheduleForm(validValues, { timezone: 'Asia/Kolkata', now: NOW })).toEqual({
      ok: true,
      body: {
        title: 'Morning inbox',
        task: 'Summarize unread email',
        frequency: 'daily',
        local_time: '08:05',
        timezone: 'Asia/Kolkata',
        delivery: 'chat',
        delivery_target: null,
      },
    });
  });

  it('sends the weekdays of a weekly schedule, in order', () => {
    const result = validateScheduleForm(
      { ...validValues, frequency: 'weekly', weekdays: ['friday', 'monday'] },
      UTC
    );

    expect(result.ok && result.body.weekdays).toEqual(['monday', 'friday']);
  });

  it('sends the day of a monthly schedule and the hours of an interval', () => {
    const monthly = validateScheduleForm(
      { ...validValues, frequency: 'monthly', dayOfMonth: 31 },
      UTC
    );
    const interval = validateScheduleForm(
      { ...validValues, frequency: 'interval', intervalHours: 6 },
      UTC
    );

    expect(monthly.ok && monthly.body.day_of_month).toBe(31);
    expect(interval.ok && interval.body).toMatchObject({ interval_hours: 6, local_time: '08:05' });
    // An interval starts today; the backend fills in the date.
    expect(interval.ok && interval.body.start_date).toBeUndefined();
  });

  it('sends the date of a one-time schedule', () => {
    const result = validateScheduleForm(
      { ...validValues, frequency: 'once', date: '2026-10-03' },
      UTC
    );

    expect(result.ok && result.body).toMatchObject({ frequency: 'once', start_date: '2026-10-03' });
  });

  it('refuses a one-time moment already past on this device', () => {
    const result = validateScheduleForm(
      { ...validValues, frequency: 'once', date: '2026-10-01', time: '11:00' },
      { timezone: deviceTimezone(), now: NOW }
    );

    expect(result.ok ? null : result.errors.date).toBe('Pick a time in the future.');
  });

  it('keeps the delivery target when results go to an app', () => {
    const result = validateScheduleForm(
      { ...validValues, delivery: 'slack', deliveryTarget: ' #team ' },
      UTC
    );

    expect(result.ok && result.body).toMatchObject({ delivery: 'slack', delivery_target: '#team' });
  });

  it('refuses an app that is not connected', () => {
    const result = validateScheduleForm(
      { ...validValues, delivery: 'slack' },
      { ...UTC, deliveries: new Set(['chat']) }
    );

    expect(result.ok ? null : result.errors.delivery).toBe(
      'Connect Slack in Tools & Connections first.'
    );
  });

  it('reports every invalid field', () => {
    const result = validateScheduleForm(
      {
        ...validValues,
        title: ' ',
        task: '',
        time: '25:00',
        frequency: 'weekly',
        weekdays: [],
      },
      UTC
    );

    expect(result.ok).toBe(false);
    expect(!result.ok && Object.keys(result.errors).sort()).toEqual([
      'task',
      'time',
      'title',
      'weekdays',
    ]);
  });

  it.each([
    [{ frequency: 'monthly', dayOfMonth: 0 }, 'dayOfMonth'],
    [{ frequency: 'monthly', dayOfMonth: 32 }, 'dayOfMonth'],
    [{ frequency: 'interval', intervalHours: 0 }, 'intervalHours'],
    [{ frequency: 'interval', intervalHours: 25 }, 'intervalHours'],
    [{ frequency: 'once', date: 'tomorrow' }, 'date'],
  ] as const)('refuses %p', (changes, field) => {
    const result = validateScheduleForm({ ...validValues, ...changes }, UTC);

    expect(!result.ok && Object.keys(result.errors)).toEqual([field]);
  });

  it('limits the title length like the backend', () => {
    const result = validateScheduleForm({ ...validValues, title: 'x'.repeat(121) }, UTC);

    expect(result.ok).toBe(false);
  });
});

describe('editing', () => {
  it('fills the form from a schedule, with defaults for fields it does not use', () => {
    const values = scheduleToValues(
      schedule({ frequency: 'weekly', weekdays: ['saturday'], delivery_target: null }),
      NOW
    );

    expect(values).toMatchObject({
      title: 'Plants',
      frequency: 'weekly',
      weekdays: ['saturday'],
      time: '09:00',
      date: '2026-10-02',
      deliveryTarget: '',
    });
  });

  it('sends the whole rule, in the schedule timezone', () => {
    const original = schedule();
    const values = {
      ...scheduleToValues(original, NOW),
      frequency: 'monthly' as const,
      dayOfMonth: 15,
    };

    const result = validateScheduleEdit(values, original, {
      timezone: original.timezone,
      now: NOW,
    });

    expect(result.ok && result.body).toMatchObject({
      frequency: 'monthly',
      day_of_month: 15,
      timezone: 'Asia/Kolkata',
      local_time: '09:00',
    });
  });

  it('keeps an interval schedule on its first day', () => {
    const original = schedule({
      frequency: 'interval',
      interval_hours: 4,
      start_date: '2026-09-20',
    });

    const result = validateScheduleEdit(
      { ...scheduleToValues(original, NOW), intervalHours: 6 },
      original,
      { timezone: original.timezone, now: NOW }
    );

    expect(result.ok && result.body).toMatchObject({ interval_hours: 6, start_date: '2026-09-20' });
  });
});

describe('availableDeliveries', () => {
  it('offers chat and the deliveries whose app is connected', () => {
    const tools = [
      { slug: 'slack', status: 'connected' },
      { slug: 'gmail', status: 'revoked' },
      { slug: 'googlecalendar', status: 'connected' },
    ] as Tool[];

    expect([...availableDeliveries(tools)].sort()).toEqual(['calendar', 'chat', 'slack']);
  });
});
