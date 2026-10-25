import { fetch as expoFetch } from 'expo/fetch';
import { streamReply } from '@/lib/api/chatStream';
import { ApiError } from '@/lib/api/client';
import type { ChatStreamEvent } from '@/lib/api/types';
import { supabase } from '@/lib/supabase';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

jest.mock('@/lib/env', () => ({
  env: { apiUrl: 'https://api.test', supabaseUrl: '', supabasePublishableKey: '' },
  isApiConfigured: true,
  isSupabaseConfigured: false,
}));

jest.mock('@/lib/supabase', () => ({
  getAccessToken: jest.fn(async () => 'token-123'),
  supabase: {
    auth: {
      getSession: jest.fn(async () => ({ data: { session: { access_token: 'token-123' } } })),
      signOut: jest.fn(async () => ({ error: null })),
    },
  },
}));

const mockFetch = expoFetch as unknown as jest.Mock;
const mockSignOut = supabase.auth.signOut as jest.Mock;

/** A response whose body yields the given byte chunks, like a network stream. */
function streamingResponse(chunks: Uint8Array[]) {
  let index = 0;
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () =>
          index < chunks.length
            ? { done: false as const, value: chunks[index++] }
            : { done: true as const, value: undefined },
      }),
    },
  };
}

/** Splits the UTF-8 bytes of `text` at the given byte offsets. */
function splitBytes(text: string, offsets: number[]): Uint8Array[] {
  const bytes = new TextEncoder().encode(text);
  const chunks: Uint8Array[] = [];
  let start = 0;
  for (const offset of [...offsets, bytes.length]) {
    chunks.push(bytes.slice(start, offset));
    start = offset;
  }
  return chunks;
}

function jsonErrorResponse(status: number, body: unknown) {
  return {
    ok: false,
    status,
    body: null,
    text: async () => JSON.stringify(body),
  };
}

const userMessage = {
  id: 'm1',
  thread_id: 't1',
  role: 'user' as const,
  content: 'Hi 👋',
  metadata: {},
  created_at: '2026-10-19T08:00:00Z',
  updated_at: '2026-10-19T08:00:00Z',
};

describe('streamReply', () => {
  let warnSpy: jest.SpyInstance;

  beforeEach(() => {
    mockFetch.mockReset();
    mockSignOut.mockClear();
    warnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  it('parses NDJSON split across chunks, skipping unknown events and non-JSON lines', async () => {
    const lines = [
      JSON.stringify({ type: 'turn_started', user_message: userMessage }),
      JSON.stringify({ type: 'text_delta', text: 'Hello ' }),
      JSON.stringify({ type: 'future_event', anything: true }),
      'this is not json',
      '',
      JSON.stringify({ type: 'text_delta', text: 'wörld ✨' }),
      // The last line has no trailing newline.
      JSON.stringify({ type: 'error', error_code: 'MODEL_ERROR', message: 'Stopped' }),
    ];
    const text = lines.join('\n');
    const bytes = new TextEncoder().encode(text);
    // Cut inside the first JSON line, inside a multi-byte character, and near the end.
    const emojiOffset = new TextEncoder().encode(text.slice(0, text.indexOf('✨'))).length + 1;
    mockFetch.mockResolvedValue(
      streamingResponse(splitBytes(text, [7, 60, emojiOffset, bytes.length - 3]))
    );

    const events: ChatStreamEvent[] = [];
    await streamReply('t1', { content: 'Hi 👋', timezone: 'UTC' }, (event) => events.push(event));

    expect(events).toEqual([
      { type: 'turn_started', user_message: userMessage },
      { type: 'text_delta', text: 'Hello ' },
      { type: 'text_delta', text: 'wörld ✨' },
      { type: 'error', error_code: 'MODEL_ERROR', message: 'Stopped' },
    ]);
    expect(warnSpy).toHaveBeenCalledTimes(1);
  });

  it('posts the message with the bearer token and NDJSON accept header', async () => {
    mockFetch.mockResolvedValue(streamingResponse([]));
    const body = {
      content: '',
      timezone: 'Asia/Kolkata',
      attachments: [{ name: 'a.png', media_type: 'image/png' as const, data: 'AAAA' }],
    };

    await streamReply('thread/1', body, () => {});

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe('https://api.test/api/v1/threads/thread%2F1/messages');
    expect(init.method).toBe('POST');
    expect(init.headers).toMatchObject({
      Authorization: 'Bearer token-123',
      Accept: 'application/x-ndjson',
      'Content-Type': 'application/json',
    });
    expect(JSON.parse(init.body)).toEqual(body);
  });

  it('rejects a refused message with the server error and does not sign out', async () => {
    mockFetch.mockResolvedValue(
      jsonErrorResponse(429, { error_code: 'RATE_LIMITED', message: 'Slow down.', detail: null })
    );

    const error = await streamReply('t1', { content: 'x', timezone: 'UTC' }, () => {}).catch(
      (caught: unknown) => caught
    );

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, code: 'RATE_LIMITED', message: 'Slow down.' });
    expect(mockSignOut).not.toHaveBeenCalled();
  });

  it('signs out once on 401, even when several requests fail together', async () => {
    mockFetch.mockResolvedValue(
      jsonErrorResponse(401, { error_code: 'UNAUTHORIZED', message: 'Session expired.' })
    );
    const send = () =>
      streamReply('t1', { content: 'x', timezone: 'UTC' }, () => {}).catch(
        (caught: unknown) => caught
      );

    const errors = await Promise.all([send(), send()]);
    // Let the shared sign-out finish.
    await new Promise((resolve) => setTimeout(resolve, 0));

    errors.forEach((error) => expect(error).toMatchObject({ status: 401 }));
    expect(mockSignOut).toHaveBeenCalledTimes(1);
  });

  it('reports a dropped connection as a stream interruption', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            throw new TypeError('Network connection lost');
          },
        }),
      },
    });

    await expect(
      streamReply('t1', { content: 'x', timezone: 'UTC' }, () => {})
    ).rejects.toMatchObject({ status: 0, code: 'stream_interrupted' });
  });
});
