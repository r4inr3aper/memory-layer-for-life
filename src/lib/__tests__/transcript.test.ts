import type { ChatMessage } from '@/lib/api/types';
import { buildTranscript } from '@/lib/transcript';

jest.mock('@/lib/supabase', () => ({
  getAccessToken: jest.fn(async () => null),
  supabase: { auth: { getSession: jest.fn(), signOut: jest.fn() } },
}));

function message(role: ChatMessage['role'], content: string, extra: Partial<ChatMessage> = {}) {
  return {
    id: `${role}-${content}`,
    thread_id: 't1',
    role,
    content,
    metadata: {},
    created_at: '2026-10-19T08:00:00Z',
    updated_at: '2026-10-19T08:00:00Z',
    ...extra,
  } satisfies ChatMessage;
}

describe('buildTranscript', () => {
  it('labels each message with its speaker, oldest first', () => {
    const transcript = buildTranscript(
      [message('user', 'Plan my week'), message('assistant', 'Here is a plan:\n- Monday: gym')],
      'Nova'
    );

    expect(transcript).toBe('You: Plan my week\n\nNova: Here is a plan:\n- Monday: gym');
  });

  it('names attached files and skips empty messages', () => {
    const transcript = buildTranscript(
      [
        message('user', '', {
          metadata: {
            attachments: [{ name: 'invoice.pdf', media_type: 'application/pdf', size_bytes: 10 }],
          },
        }),
        message('assistant', '   '),
      ],
      'Cooper'
    );

    expect(transcript).toBe('You: [Attached: invoice.pdf]');
  });

  it('is empty for a thread without messages', () => {
    expect(buildTranscript([], 'Cooper')).toBe('');
  });
});
