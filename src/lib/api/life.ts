/**
 * Life API: what is open in the user's life, checking items off, reminders, the daily
 * brief, and searching chats. To-dos are memories, so writing and editing one goes through
 * `memories.ts` (`createMemory`, `updateMemory` with `due_on` and `remind_at`).
 */

import { apiRequest } from '@/lib/api/client';
import type { BriefPreview, LifeOverview, MemoryItem, MessageHit } from '@/lib/api/types';

export function getLife(signal?: AbortSignal): Promise<LifeOverview> {
  return apiRequest<LifeOverview>('/me/life', { signal });
}

/** Today's brief as it stands now, without sending it. */
export function getBriefPreview(signal?: AbortSignal): Promise<BriefPreview> {
  return apiRequest<BriefPreview>('/me/life/brief', { signal });
}

/**
 * `complete`: done (clears its reminder). `drop`: no longer planned. `reopen`: undo either.
 */
export function closeItem(
  memoryId: string,
  action: 'complete' | 'drop' | 'reopen'
): Promise<MemoryItem> {
  return apiRequest<MemoryItem>(`/me/memories/${encodeURIComponent(memoryId)}/${action}`, {
    method: 'POST',
  });
}

/** Sets (or with `null` clears) when an item is due and when to remind the user. */
export function scheduleItem(
  memoryId: string,
  changes: { due_on?: string | null; remind_at?: string | null }
): Promise<MemoryItem> {
  return apiRequest<MemoryItem>(`/me/memories/${encodeURIComponent(memoryId)}`, {
    method: 'PATCH',
    body: changes,
  });
}

/** The user's chat messages containing the query's words, best first. */
export async function searchMessages(
  query: string,
  limit = 20,
  signal?: AbortSignal
): Promise<MessageHit[]> {
  const result = await apiRequest<{ items: MessageHit[] }>('/me/messages/search', {
    method: 'POST',
    body: { query, limit },
    signal,
  });
  return result.items;
}
