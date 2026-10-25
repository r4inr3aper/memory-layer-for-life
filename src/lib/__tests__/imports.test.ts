import type { ChatImport } from '@/lib/api/types';
import {
  importEstimate,
  importProgressText,
  plannedConversations,
  sinceChoices,
} from '@/lib/imports';

function chatImport(overrides: Partial<ChatImport> = {}): ChatImport {
  return {
    id: 'i1',
    file_name: 'chat.txt',
    status: 'previewed',
    participants: [
      { name: 'Ada', messages: 400, conversations: 250 },
      { name: 'Priya', messages: 380, conversations: 260 },
    ],
    message_count: 780,
    all_conversations: 320,
    first_message_at: null,
    last_message_at: null,
    owner_name: null,
    since: null,
    unit_count: null,
    cost_per_conversation: '0.04',
    currency: 'INR',
    progress: null,
    created_at: '2026-10-25T10:00:00Z',
    ...overrides,
  };
}

describe('import planning', () => {
  it('counts the chosen person’s conversations, or all of them, within the cap', () => {
    expect(plannedConversations(chatImport(), 'Ada', true)).toBe(200);
    expect(plannedConversations(chatImport(), 'Ada', true, 300)).toBe(250);
    expect(plannedConversations(chatImport(), 'Ada', false, 300)).toBe(300);
    expect(plannedConversations(chatImport(), null, true)).toBe(0);
  });

  it('says what the extractions will cost when the price is known', () => {
    expect(importEstimate(chatImport(), 100)).toBe('Up to 100 extractions, about ₹4.00');
    expect(importEstimate(chatImport({ cost_per_conversation: null }), 1)).toBe(
      'Up to 1 extraction'
    );
  });

  it('offers everything or a recent period', () => {
    expect(sinceChoices('2026-10-25').map((choice) => choice.value)).toEqual([
      null,
      '2025-10-25',
      '2026-07-26',
      '2026-09-25',
    ]);
  });

  it('describes progress while the pipeline works and when it is done', () => {
    expect(importProgressText(chatImport())).toBe('Not started');
    expect(
      importProgressText(
        chatImport({ progress: { done: 45, failed: 0, waiting: 75, memories: 3 } })
      )
    ).toBe('45 of 120 done, 3 memories so far');
    expect(
      importProgressText(
        chatImport({ progress: { done: 118, failed: 2, waiting: 0, memories: 1 } })
      )
    ).toBe('Finished: 1 memory; 2 could not be read');
  });
});
