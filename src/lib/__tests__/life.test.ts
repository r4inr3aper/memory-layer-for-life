import {
  addDays,
  daysBetween,
  dueChoices,
  dueLabel,
  isoDate,
  localIsoTime,
  reminderLabel,
  snippetParts,
  snoozeChoices,
} from '@/lib/life';

// Thursday 1 October 2026.
const TODAY = '2026-10-01';

describe('dates', () => {
  it('converts between local dates and YYYY-MM-DD', () => {
    expect(isoDate(new Date(2026, 9, 1, 23, 59))).toBe('2026-10-01');
    expect(addDays(TODAY, 31)).toBe('2026-11-01');
    expect(addDays(TODAY, -1)).toBe('2026-09-30');
    expect(daysBetween(TODAY, '2026-10-08')).toBe(7);
  });

  it('labels due dates relative to today', () => {
    expect(dueLabel(TODAY, TODAY)).toBe('Today');
    expect(dueLabel('2026-10-02', TODAY)).toBe('Tomorrow');
    expect(dueLabel('2026-09-30', TODAY)).toBe('Yesterday');
    expect(dueLabel('2026-10-03', TODAY)).toMatch(/Sat/);
    expect(dueLabel('2026-10-20', TODAY)).toMatch(/20/);
  });

  it('labels reminders with the day and the time', () => {
    const now = new Date(2026, 9, 1, 10, 0);
    expect(reminderLabel(new Date(2026, 9, 1, 18, 0).toISOString(), now)).toBe('Today 18:00');
    expect(reminderLabel(new Date(2026, 9, 2, 9, 5).toISOString(), now)).toBe('Tomorrow 09:05');
  });

  it('turns a local date and time into an ISO time', () => {
    expect(new Date(localIsoTime('2026-10-02', '18:30')).getTime()).toBe(
      new Date(2026, 9, 2, 18, 30).getTime()
    );
  });
});

describe('quick choices', () => {
  it('offers today, tomorrow, the weekend, and next week', () => {
    expect(dueChoices(TODAY)).toEqual([
      { label: 'Today', value: '2026-10-01' },
      { label: 'Tomorrow', value: '2026-10-02' },
      { label: 'This weekend', value: '2026-10-03' },
      { label: 'Next week', value: '2026-10-05' },
    ]);
    // On a Saturday the weekend is the next one, and Monday is two days away.
    expect(dueChoices('2026-10-03')[2].value).toBe('2026-10-10');
    expect(dueChoices('2026-10-03')[3].value).toBe('2026-10-05');
  });

  it('snoozes to sensible times, all in the future', () => {
    const morning = new Date(2026, 9, 1, 10, 0);
    const labels = snoozeChoices(morning).map((choice) => choice.label);
    expect(labels).toEqual(['In 1 hour', 'This evening', 'Tomorrow morning', 'Next Monday']);
    for (const choice of snoozeChoices(morning)) {
      expect(new Date(choice.value).getTime()).toBeGreaterThan(morning.getTime());
    }
    const evening = new Date(2026, 9, 1, 20, 0);
    expect(snoozeChoices(evening).map((choice) => choice.label)).not.toContain('This evening');
  });
});

describe('snippetParts', () => {
  it('marks the matched words', () => {
    expect(snippetParts('The <<electricity>> bill was <<2400>>')).toEqual([
      { text: 'The ', match: false },
      { text: 'electricity', match: true },
      { text: ' bill was ', match: false },
      { text: '2400', match: true },
    ]);
    expect(snippetParts('no matches')).toEqual([{ text: 'no matches', match: false }]);
  });
});
