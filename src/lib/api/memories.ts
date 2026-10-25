/**
 * Memories API: the user's memories with their evidence and history, writing and
 * correcting them, the review inbox, and the people in them.
 */

import { apiRequest } from '@/lib/api/client';
import type {
  CreateMemoryBody,
  MemoryDetail,
  MemoryItem,
  MemoryListParams,
  MemorySearchResult,
  Page,
  PageParams,
  Person,
  PersonDetail,
  ReviewInbox,
  SuggestionKind,
  UpdateMemoryBody,
} from '@/lib/api/types';

/** Newest first; by default the memories that may still be true (proposed and active). */
export function listMyMemories(
  params: MemoryListParams = {},
  signal?: AbortSignal
): Promise<Page<MemoryItem>> {
  return apiRequest<Page<MemoryItem>>('/me/memories', { query: { ...params }, signal });
}

/** The most results one search returns (the backend's MAX_SEARCH_RESULTS). */
export const MAX_MEMORY_SEARCH_RESULTS = 25;

/** Words, names, and meaning. The same text appears once; sensitive memories are marked. */
export function searchMyMemories(
  query: string,
  limit = 20,
  signal?: AbortSignal
): Promise<MemorySearchResult> {
  return apiRequest<MemorySearchResult>('/me/memories/search', {
    method: 'POST',
    // A larger limit is refused outright (422), so it is capped here.
    body: { query, limit: Math.min(limit, MAX_MEMORY_SEARCH_RESULTS) },
    signal,
  });
}

export function getMemory(memoryId: string, signal?: AbortSignal): Promise<MemoryDetail> {
  return apiRequest<MemoryDetail>(`/me/memories/${encodeURIComponent(memoryId)}`, { signal });
}

export function createMemory(body: CreateMemoryBody): Promise<MemoryItem> {
  return apiRequest<MemoryItem>('/me/memories', { method: 'POST', body });
}

/** New text returns a new version with its own id; kind and sensitivity change in place. */
export function updateMemory(memoryId: string, body: UpdateMemoryBody): Promise<MemoryItem> {
  return apiRequest<MemoryItem>(`/me/memories/${encodeURIComponent(memoryId)}`, {
    method: 'PATCH',
    body,
  });
}

/** Deletes the memory with its older versions and merged duplicates. Returns how many. */
export async function deleteMemory(memoryId: string): Promise<number> {
  const result = await apiRequest<{ deleted: number }>(
    `/me/memories/${encodeURIComponent(memoryId)}`,
    { method: 'DELETE' }
  );
  return result.deleted;
}

type MemoryAction = 'accept' | 'retract' | 'restore';

/** Accept a proposed memory, mark one as wrong, or restore one marked as wrong. */
export function changeMemoryStatus(memoryId: string, action: MemoryAction): Promise<MemoryItem> {
  return apiRequest<MemoryItem>(`/me/memories/${encodeURIComponent(memoryId)}/${action}`, {
    method: 'POST',
  });
}

/**
 * Keep `memoryId` over `otherId`. `merge` takes the other's evidence (a duplicate);
 * `replace` does not (the other is out of date). The other becomes superseded.
 */
export function keepMemory(
  memoryId: string,
  otherId: string,
  how: 'merge' | 'replace'
): Promise<MemoryItem> {
  return apiRequest<MemoryItem>(`/me/memories/${encodeURIComponent(memoryId)}/${how}`, {
    method: 'POST',
    body: { other_memory_id: otherId },
  });
}

export function getReviewInbox(signal?: AbortSignal): Promise<ReviewInbox> {
  return apiRequest<ReviewInbox>('/me/memories/review', { signal });
}

/** Accepts the proposed ones among these (at most 100). Returns how many. */
export async function acceptMemories(memoryIds: string[]): Promise<number> {
  const result = await apiRequest<{ accepted: number }>('/me/memories/review/accept', {
    method: 'POST',
    body: { memory_ids: memoryIds },
  });
  return result.accepted;
}

export function dismissSuggestion(
  firstMemoryId: string,
  secondMemoryId: string,
  kind: SuggestionKind
): Promise<void> {
  return apiRequest<void>('/me/memories/review/dismiss', {
    method: 'POST',
    body: { first_memory_id: firstMemoryId, second_memory_id: secondMemoryId, kind },
  });
}

/** Saves a memory the user wrote from a held-back message; it rests on that message. */
export function saveHeldBack(runId: string, body: CreateMemoryBody): Promise<MemoryItem> {
  return apiRequest<MemoryItem>(`/me/memories/held-back/${encodeURIComponent(runId)}/save`, {
    method: 'POST',
    body,
  });
}

export function dismissHeldBack(runId: string): Promise<void> {
  return apiRequest<void>(`/me/memories/held-back/${encodeURIComponent(runId)}/dismiss`, {
    method: 'POST',
  });
}

/** People, places, and things current memories mention, most mentioned first. */
export function listPeople(
  params: PageParams & { entity_type?: string } = {},
  signal?: AbortSignal
): Promise<Page<Person>> {
  return apiRequest<Page<Person>>('/me/people', { query: { ...params }, signal });
}

/** A merged person's id answers with the person they were merged into. */
export function getPerson(personId: string, signal?: AbortSignal): Promise<PersonDetail> {
  return apiRequest<PersonDetail>(`/me/people/${encodeURIComponent(personId)}`, { signal });
}

/** The old name is kept as another name. */
export function renamePerson(personId: string, name: string): Promise<PersonDetail> {
  return apiRequest<PersonDetail>(`/me/people/${encodeURIComponent(personId)}`, {
    method: 'PATCH',
    body: { name },
  });
}

/** `otherId` is merged into `personId`, then gone. */
export function mergePeople(personId: string, otherId: string): Promise<PersonDetail> {
  return apiRequest<PersonDetail>(`/me/people/${encodeURIComponent(personId)}/merge`, {
    method: 'POST',
    body: { other_person_id: otherId },
  });
}
