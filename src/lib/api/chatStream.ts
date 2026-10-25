/**
 * Chat Reply Stream
 *
 * `POST /threads/{id}/messages` stores the user's message and streams the assistant's
 * reply as newline-delimited JSON. React Native's global `fetch` cannot read a response
 * body incrementally, so this uses `expo/fetch`, which can.
 */

import { fetch } from 'expo/fetch';
import {
  ApiError,
  authHeaders,
  buildApiUrl,
  failedResponseError,
  isAbortError,
  toNetworkError,
} from '@/lib/api/client';
import { threadPath } from '@/lib/api/threads';
import type { ChatStreamEvent, SendMessageBody } from '@/lib/api/types';

const STREAM_EVENT_TYPES: ReadonlySet<string> = new Set<ChatStreamEvent['type']>([
  'turn_started',
  'text_delta',
  'tool_started',
  'browser',
  'connect_link',
  'final',
  'error',
]);

/**
 * Sends a message and calls `onEvent` for each event of the reply, in order. Resolves
 * when the stream ends. Rejects with an `ApiError` when the server refuses the message
 * (404, 409, 422, 503: these are plain JSON errors, not streamed) or cannot be reached,
 * and with an abort error when `signal` is aborted.
 */
export async function streamReply(
  threadId: string,
  body: SendMessageBody,
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const url = buildApiUrl(`${threadPath(threadId)}/messages`);
  const headers = {
    ...(await authHeaders()),
    Accept: 'application/x-ndjson',
    'Content-Type': 'application/json',
  };

  let response: Awaited<ReturnType<typeof fetch>>;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    throw toNetworkError(error, signal);
  }

  if (!response.ok) {
    // Signs out on a 401, like every other API call.
    throw await failedResponseError(response);
  }

  if (!response.body) {
    throw streamInterrupted(null, signal);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    let chunk: Awaited<ReturnType<typeof reader.read>>;
    try {
      chunk = await reader.read();
    } catch (error) {
      throw streamInterrupted(error, signal);
    }
    if (chunk.done) {
      break;
    }

    buffer += decoder.decode(chunk.value, { stream: true });
    const lines = buffer.split('\n');
    // The last piece is an incomplete line until its newline arrives.
    buffer = lines.pop() ?? '';
    lines.forEach((line) => emitLine(line, onEvent));
  }

  emitLine(buffer + decoder.decode(), onEvent);
}

/** The server keeps writing and stores the reply even when the client disconnects. */
function streamInterrupted(error: unknown, signal?: AbortSignal): unknown {
  if (isAbortError(error, signal)) {
    return error;
  }
  return new ApiError(
    0,
    'stream_interrupted',
    'The connection dropped before the reply finished. Reopen this chat to see it.'
  );
}

function emitLine(line: string, onEvent: (event: ChatStreamEvent) => void) {
  const trimmed = line.trim();
  if (!trimmed) {
    return;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch {
    console.warn('[chatStream] Skipping a reply stream line that is not JSON');
    return;
  }

  if (isChatStreamEvent(parsed)) {
    onEvent(parsed);
  }
}

/** Events of unknown types are skipped, so the server can add new ones safely. */
function isChatStreamEvent(value: unknown): value is ChatStreamEvent {
  return (
    typeof value === 'object' &&
    value !== null &&
    STREAM_EVENT_TYPES.has(String((value as { type?: unknown }).type))
  );
}
