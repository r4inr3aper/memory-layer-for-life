import type { HeldBack, MemoryEvent, MemoryItem } from '@/lib/api/types';
import {
  groupMemoriesByTime,
  heldBackDraft,
  heldBackReasonText,
  historyText,
  memoryStatusLabel,
  memoryTypeLabel,
  suggestionText,
  timelineTitle,
  validateMemoryContent,
} from '@/lib/memories';

function memory(id: string, createdAt: string): MemoryItem {
  return {
    id,
    memory_type: 'semantic_fact',
    content: `Memory ${id}`,
    normalized_content: null,
    status: 'proposed',
    confidence: 0.9,
    valid_from: null,
    valid_until: null,
    observed_at: null,
    supersedes_memory_id: null,
    metadata: {},
    created_at: createdAt,
    updated_at: createdAt,
    created_by: 'pipeline',
    sensitive: false,
    state: null,
    due_on: null,
    remind_at: null,
    closed_at: null,
    close_reason: null,
  };
}

function event(action: MemoryEvent['action'], details: Record<string, unknown> = {}): MemoryEvent {
  return { id: action, action, details, created_at: '2026-10-24T10:00:00Z' };
}

describe('memoryTypeLabel', () => {
  it('names the memory types the backend makes', () => {
    expect(memoryTypeLabel('semantic_fact')).toBe('Fact');
    expect(memoryTypeLabel('preference')).toBe('Preference');
    expect(memoryTypeLabel('open_loop')).toBe('Open loop');
    expect(memoryTypeLabel('financial_note')).toBe('Money');
  });

  it('reads a type added later instead of hiding it', () => {
    expect(memoryTypeLabel('travel_plan')).toBe('Travel plan');
    expect(memoryTypeLabel('')).toBe('Memory');
  });
});

describe('memoryStatusLabel', () => {
  it('says what each status means to the user', () => {
    expect(memoryStatusLabel('proposed')).toBe('To review');
    expect(memoryStatusLabel('active')).toBe('Accepted');
    expect(memoryStatusLabel('superseded')).toBe('Replaced');
    expect(memoryStatusLabel('retracted')).toBe('Marked wrong');
  });
});

describe('timeline', () => {
  const now = new Date(2026, 9, 24, 15, 0);

  it('names recent days and then months', () => {
    expect(timelineTitle(new Date(2026, 9, 24, 1, 0).toISOString(), now)).toBe('Today');
    expect(timelineTitle(new Date(2026, 9, 23, 23, 0).toISOString(), now)).toBe('Yesterday');
    expect(timelineTitle(new Date(2026, 9, 19, 9, 0).toISOString(), now)).toBe('This week');
    expect(timelineTitle(new Date(2026, 9, 17, 9, 0).toISOString(), now)).toContain('2026');
  });

  it('groups memories in order, extending a section across pages', () => {
    const sections = groupMemoriesByTime(
      [
        memory('a', new Date(2026, 9, 24, 12).toISOString()),
        memory('b', new Date(2026, 9, 24, 8).toISOString()),
        memory('c', new Date(2026, 9, 23, 8).toISOString()),
        memory('d', new Date(2026, 8, 2, 8).toISOString()),
        memory('e', new Date(2026, 8, 1, 8).toISOString()),
      ],
      now
    );

    expect(sections.map((section) => section.title)).toEqual([
      'Today',
      'Yesterday',
      expect.stringContaining('2026'),
    ]);
    expect(sections.map((section) => section.data.map((item) => item.id))).toEqual([
      ['a', 'b'],
      ['c'],
      ['d', 'e'],
    ]);
    expect(groupMemoriesByTime([], now)).toEqual([]);
  });
});

describe('historyText', () => {
  it('describes what the user did', () => {
    expect(historyText(event('created'))).toBe('You wrote it');
    expect(historyText(event('created', { processing_run_id: 'r' }))).toBe(
      'You saved it from a message Cooper held back'
    );
    expect(historyText(event('accepted'))).toBe('You accepted it');
    expect(historyText(event('retracted'))).toBe('You marked it as wrong');
    expect(historyText(event('restored'))).toBe('You restored it');
    expect(historyText(event('suggestion_dismissed'))).toBe(
      'You kept it apart from a similar memory'
    );
  });

  it('spells out edits, corrections, and replacements', () => {
    expect(
      historyText(
        event('edited', {
          changes: {
            memory_type: { from: 'semantic_fact', to: 'preference' },
            sensitive: { from: false, to: true },
          },
        })
      )
    ).toBe('Kind changed to Preference · Marked sensitive');
    expect(historyText(event('corrected', { previous_content: 'Lives in Pune.' }))).toBe(
      'You corrected it. It said: "Lives in Pune."'
    );
    expect(historyText(event('superseded', { reason: 'corrected' }))).toBe(
      'Replaced by your corrected version'
    );
    expect(historyText(event('superseded', { reason: 'merged' }))).toBe(
      'Merged into another memory'
    );
    expect(historyText(event('superseded', { reason: 'replaced' }))).toBe(
      'Replaced by a newer memory'
    );
    expect(historyText(event('merged', { content: 'Lives in Pune.' }))).toBe(
      'Merged with "Lives in Pune."'
    );
    expect(historyText(event('replaced', {}))).toBe('Replaced another memory');
  });
});

describe('review wording', () => {
  const heldBack: HeldBack = {
    run_id: 'r',
    held_at: null,
    reason: 'unclear',
    messages: [
      { raw_message_id: '1', content: '  the thing with K ', sent_at: null, thread_id: null },
      { raw_message_id: '2', content: 'same as before', sent_at: null, thread_id: null },
    ],
  };

  it('explains suggestions and held-back messages', () => {
    expect(suggestionText('duplicate')).toBe('These look like the same memory.');
    expect(suggestionText('conflict')).toContain('may not both be true');
    expect(heldBackReasonText('unclear')).toContain("wasn't sure");
    expect(heldBackReasonText('unreadable')).toContain("couldn't read");
  });

  it('prefills a held-back message as one line of text', () => {
    expect(heldBackDraft(heldBack)).toBe('the thing with K same as before');
  });

  it('checks a memory before it is saved', () => {
    expect(validateMemoryContent('   ')).toBe('Write what Cooper should remember.');
    expect(validateMemoryContent('x'.repeat(2001))).toContain('2000');
    expect(validateMemoryContent('Priya lives in Pune')).toBeNull();
  });
});
